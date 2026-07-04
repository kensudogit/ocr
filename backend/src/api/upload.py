"""ファイルアップロード & OCR 処理 API。

処理フロー（全体 7 ステップ）:
  Step 1: 入力受付（単一 / 一括 / スマホ撮影バッチ）
  Step 2: 画像前処理（傾き補正・感熱紙強調・ノイズ除去・複数枚分割）
  Step 3: AI-OCR（VLM で構造化抽出）
  Step 4: ルール層（顧問先別の過去仕訳から勘定科目・税区分サジェスト）
  Step 5: 信頼度判定（自動確定 / 要確認 / 手入力 3段階＋検算）
  → 以降は確認 UI（フロントエンド）で担当者が処理
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.ai_deployment import AiDeploymentMode, get_deployment_config
from src.core.audit_log import AuditEventType, get_audit_logger
from src.core.classifier import DocumentClassifier
from src.core.confidence_scorer import ConfidenceScorer, ConfidenceTier
from src.core.electronic_bookkeeping import ElectronicBookkeepingStorage, ElectronicBookkeepingValidator
from src.core.extractor import DataExtractor
from src.core.invoice_validator import InvoiceNumberValidator
from src.core.pii_masker import PiiMasker
from src.core.preprocessor import ImagePreprocessor
from src.core.rule_engine import get_rule_engine
from src.core.vlm_extractor import VlmExtractor
from src.db.database import get_db
from src.db.models import (
    AuditLog,
    BatchJob,
    Client,
    ConfidenceTierValue,
    DocStatus,
    Document,
    ExtractedData,
    JournalHistory,
    LineItem,
    ScanTimestamp,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"])

# ── シングルトン ──────────────────────────────────────────────────────
_preprocessor      = ImagePreprocessor(
    enhance_thermal=settings.enhance_thermal_paper,
    auto_rotate=settings.auto_rotate,
    denoise_level=settings.denoise_level,
)
_vlm_extractor     = VlmExtractor()
_classifier        = DocumentClassifier()
_scorer            = ConfidenceScorer()
_rule_engine       = get_rule_engine()
_invoice_validator = InvoiceNumberValidator()
_pii_masker        = PiiMasker(
    mask_bank_accounts=settings.pii_mask_bank_accounts,
    mask_my_number=settings.pii_mask_my_number,
    mask_card_numbers=settings.pii_mask_card_numbers,
    mask_phone_numbers=settings.pii_mask_phone_numbers,
)
_eb_storage        = ElectronicBookkeepingStorage(settings.originals_dir)
_eb_validator      = ElectronicBookkeepingValidator()
_audit             = get_audit_logger()
_deploy_config     = get_deployment_config()


# ── ユーティリティ ────────────────────────────────────────────────────

def _validate_file(file: UploadFile) -> None:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"未対応の拡張子: {suffix}。対応: {settings.allowed_extensions}",
        )


async def _save_file(file: UploadFile) -> tuple[str, str, int, bytes]:
    suffix = Path(file.filename or "file").suffix.lower()
    stored_name = f"{uuid.uuid4()}{suffix}"
    dest = Path(settings.upload_dir) / stored_name
    content = await file.read()
    dest.write_bytes(content)
    return stored_name, str(dest), len(content), content


def _read_file_bytes(file_path: str) -> bytes:
    return Path(file_path).read_bytes()


async def _load_rule_engine_for_client(client_id: str | None, db: AsyncSession) -> None:
    """顧問先の過去仕訳をDBから読み込みルールエンジンにロードする。"""
    if not client_id:
        return
    stmt = select(JournalHistory).where(
        JournalHistory.client_id == uuid.UUID(client_id)
    ).order_by(JournalHistory.use_count.desc()).limit(500)
    history = (await db.execute(stmt)).scalars().all()
    tuples = [(h.vendor_name, h.account_title, h.tax_category) for h in history]
    _rule_engine.load_from_history(tuples, client_id=client_id)


async def _clear_existing_ocr_results(doc_id: uuid.UUID, db: AsyncSession) -> None:
    """再処理時に既存の OCR 結果を削除する（UNIQUE 制約違反を防ぐ）。"""
    await db.execute(delete(LineItem).where(LineItem.document_id == doc_id))
    await db.execute(delete(ExtractedData).where(ExtractedData.document_id == doc_id))
    await db.execute(delete(ScanTimestamp).where(ScanTimestamp.document_id == doc_id))
    await db.flush()


# ── メイン処理パイプライン ────────────────────────────────────────────

async def _process_document(
    doc_id: uuid.UUID,
    db: AsyncSession,
    client_id: str | None = None,
) -> None:
    """全 7 ステップの OCR 処理パイプラインを実行する。"""
    stmt = select(Document).where(Document.id == doc_id)
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if not doc:
        return

    doc.status = DocStatus.PROCESSING
    doc.processing_error = None
    doc.review_flags = None
    doc.approved_at = None
    doc.approved_by = None
    await _clear_existing_ocr_results(doc_id, db)
    await db.flush()

    start = time.perf_counter()
    try:
        # DB の file_content (base64) を優先し、なければファイルシステムから読む
        if doc.file_content:
            raw_bytes = base64.b64decode(doc.file_content)
        else:
            raw_bytes = _read_file_bytes(doc.file_path)

        # ── 電子帳簿保存法: 原本保存 & 要件検証 ─────────────────
        image_hash, orig_path = _eb_storage.save_original(
            raw_bytes, str(doc_id), Path(doc.file_path).suffix
        )
        eb_result = _eb_validator.validate(raw_bytes, filename=doc.original_filename)

        # スキャンタイムスタンプ記録（DB 保存）
        from datetime import datetime as _dt_eb
        scan_ts = ScanTimestamp(
            document_id=doc_id,
            image_hash=image_hash,
            scan_datetime=eb_result.scan_datetime,
            scan_dpi=eb_result.estimated_dpi,
            color_mode=eb_result.color_mode,
            file_size_bytes=eb_result.file_size_bytes,
            input_user=client_id or "system",
            input_datetime=_dt_eb.now(),
            method="substitute",
            is_compliant=eb_result.is_compliant,
            compliance_violations=eb_result.violations or None,
        )
        db.add(scan_ts)

        if not eb_result.is_compliant:
            logger.warning(
                "電子帳簿保存法要件未達 doc=%s: %s",
                doc_id, eb_result.violations
            )

        # ── Step 2: 画像前処理 ────────────────────────────────────
        # PDF → 画像変換
        if doc.mime_type == "application/pdf" or doc.file_path.endswith(".pdf"):
            images_bytes = await asyncio.to_thread(_pdf_to_images, raw_bytes)
            if not images_bytes:
                raise ValueError(
                    "PDF を画像に変換できませんでした（PyMuPDF/pdf2image が利用不可）"
                )
            doc.page_count = len(images_bytes)
        else:
            images_bytes = [raw_bytes]

        prep_results = []

        for page_bytes in images_bytes:
            prep = await asyncio.to_thread(_preprocessor.process, page_bytes)
            prep_results.append(prep)

        # 1ページ目で書類分類
        first_prep = prep_results[0]
        aspect = first_prep.final_size[0] / max(first_prep.final_size[1], 1)

        # ── Step 3: AI-OCR（VLM）────────────────────────────────
        # ルールエンジンを顧問先の過去仕訳でロード
        if client_id:
            await _load_rule_engine_for_client(client_id, db)

        # ハイブリッドモード: 画像のメタデータ（テキスト部分）を PII マスク
        # ※ VLM には画像を直接送るため、テキストベースマスクは OCR 結果に適用
        pii_mask_applied = _deploy_config.requires_pii_masking

        # VLM で最初のページ（代表ページ）を解析
        vlm_result = await _vlm_extractor.extract(
            first_prep.pil_image,
            client_id=client_id,
        )
        fields = vlm_result.fields

        # ── ハイブリッド: OCR テキストの PII マスク確認 ──────────
        if pii_mask_applied and doc.ocr_raw_text:
            mask_result = _pii_masker.mask(doc.ocr_raw_text)
            if mask_result.mask_count > 0:
                logger.info(
                    "PII マスク適用: doc=%s, マスク件数=%d",
                    doc_id, mask_result.mask_count
                )

        # 書類分類（VLM の doc_type 提案 + classifier）
        clf = _classifier.classify(
            "",
            is_thermal=first_prep.is_thermal_paper,
            image_aspect_ratio=aspect,
        )
        doc_type = vlm_result.raw_json.get("doc_type") or clf.doc_type
        doc.doc_type = doc_type
        doc.doc_type_confidence = max(clf.confidence, vlm_result.confidence_hint)
        doc.vlm_model_used = vlm_result.model_used

        # OCR 生テキスト（VLM 生テキストまたは fallback テキスト）
        doc.ocr_raw_text = "\n".join(
            f"{k}: {v}"
            for k, v in vlm_result.raw_json.items()
            if v is not None and k not in ("line_items",)
        ) if not vlm_result.fallback_used else ""

        doc.preprocessing_applied = {
            "steps": first_prep.applied_steps,
            "skew_angle": first_prep.skew_angle,
            "is_thermal": first_prep.is_thermal_paper,
            "quality_score": first_prep.confidence,
            "vlm_fallback": vlm_result.fallback_used,
        }

        # ── インボイス登録番号ルールベース検証（AI 任せにしない）────
        # VLM の結果をルールベースで検証・補正する
        ocr_text_for_validation = doc.ocr_raw_text or ""
        invoice_validation = _invoice_validator.extract_best(ocr_text_for_validation)
        if invoice_validation.number:
            # ルールベースで抽出した番号を優先（AI 結果を上書き）
            fields.vendor_registration_no = invoice_validation.number
            if not invoice_validation.is_valid:
                # チェックデジット不一致 → 要確認フラグ
                doc.review_flags = (doc.review_flags or []) + [
                    f"インボイス番号要確認: {invoice_validation.number}（チェックデジット不一致）"
                ]
                logger.warning(
                    "インボイス番号チェックデジット不一致: doc=%s, number=%s",
                    doc_id, invoice_validation.number
                )
        elif fields.vendor_registration_no:
            # VLM が提案した番号をルールベースで再検証
            recheck = _invoice_validator.validate(fields.vendor_registration_no)
            if not recheck.is_valid:
                doc.review_flags = (doc.review_flags or []) + [
                    f"インボイス番号要確認: {fields.vendor_registration_no}"
                ]

        # ── Step 4: ルール層（勘定科目・税区分サジェスト）──────────
        rule_suggestion = _rule_engine.suggest(
            vendor_name=fields.vendor_name,
            client_id=client_id,
            current_account_title=fields.account_title,
            current_tax_category=vlm_result.raw_json.get("tax_category_suggestion"),
        )
        # ルール提案でフィールドを上書き（高信頼度の場合のみ）
        if rule_suggestion.confidence > 0.70:
            fields.account_title = rule_suggestion.account_title or fields.account_title
        tax_category_final = (
            rule_suggestion.tax_category
            or vlm_result.raw_json.get("tax_category_suggestion")
            or "課税仕入10%"
        )

        # ── Step 5: 信頼度スコアリング & 3段階分類 ──────────────
        scoring = _scorer.score(
            fields,
            vlm_confidence=vlm_result.confidence_hint,
            rule_confidence=rule_suggestion.confidence,
        )

        # 信頼度情報を Document に記録
        doc.confidence_tier  = scoring.tier.value
        doc.confidence_score = scoring.overall_score
        doc.arithmetic_check_ok = scoring.arithmetic_ok
        doc.arithmetic_diff  = scoring.arithmetic_diff
        doc.review_flags     = scoring.flags + scoring.review_reasons

        # 自動確定の場合は自動承認
        if scoring.tier == ConfidenceTier.AUTO_CONFIRMED:
            doc.status = DocStatus.APPROVED
            from datetime import datetime as _dt
            doc.approved_at = _dt.now()
            doc.approved_by = "AUTO"
        else:
            doc.status = DocStatus.PENDING

        # ── ExtractedData 保存 ────────────────────────────────────
        ex = ExtractedData(
            document_id=doc.id,
            transaction_date=fields.transaction_date,
            vendor_name=fields.vendor_name,
            vendor_address=fields.vendor_address,
            vendor_phone=fields.vendor_phone,
            vendor_registration_no=fields.vendor_registration_no,
            total_amount=fields.total_amount,
            subtotal_amount=fields.subtotal_amount,
            tax_amount_10=fields.tax_amount_10,
            tax_amount_8=fields.tax_amount_8,
            invoice_number=fields.invoice_number,
            payment_method=fields.payment_method,
            account_title=fields.account_title,
            tax_category=tax_category_final,
            confidence_scores=scoring.field_scores,
        )
        db.add(ex)

        # LineItem 保存
        for i, item in enumerate(fields.line_items):
            db.add(LineItem(
                document_id=doc.id,
                sort_order=i,
                description=item.get("description"),
                quantity=item.get("quantity"),
                unit_price=item.get("unit_price"),
                amount=item.get("amount"),
                tax_rate=item.get("tax_rate"),
            ))

        from datetime import datetime as _dt2
        doc.processed_at = _dt2.now()

    except Exception as exc:
        logger.exception("OCR 処理エラー (doc_id=%s): %s", doc_id, exc)
        doc.status = DocStatus.UPLOADED
        doc.processing_error = str(exc)
        try:
            await db.flush()
        except Exception as flush_exc:
            logger.exception("flush 失敗 (doc_id=%s): %s", doc_id, flush_exc)
            raise
        return

    try:
        await db.flush()
    except Exception as exc:
        logger.exception("OCR 結果保存エラー (doc_id=%s): %s", doc_id, exc)
        doc.status = DocStatus.UPLOADED
        doc.processing_error = str(exc)
        await db.flush()
        return

    elapsed = (time.perf_counter() - start) * 1000
    logger.info(
        "処理完了 doc_id=%s tier=%s score=%.2f elapsed=%.0fms",
        doc_id, doc.confidence_tier, doc.confidence_score or 0, elapsed
    )


def _pdf_to_images(pdf_bytes: bytes) -> list[bytes]:
    """PDF バイト列を PNG 画像バイト列のリストに変換する。

    優先順位:
      1. PyMuPDF (fitz) — requirements-poc.txt に含まれる軽量ライブラリ
      2. pdf2image (poppler 必要) — ローカル環境用フォールバック
      3. 変換不可の場合は空リストを返す（処理エラーを上流で処理）
    """
    import io as _io

    # ── PyMuPDF (fitz) ────────────────────────────────────────
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        result = []
        for page in doc:
            # dpi=200 相当: zoom = 200/72 ≈ 2.78
            mat = fitz.Matrix(200 / 72, 200 / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            result.append(pix.tobytes("png"))
        doc.close()
        logger.debug("PyMuPDF で PDF を %d ページ変換しました", len(result))
        return result
    except ImportError:
        pass  # PyMuPDF 未インストール → 次を試みる
    except Exception as exc:
        logger.warning("PyMuPDF PDF 変換エラー: %s", exc)

    # ── pdf2image (poppler 必要) ──────────────────────────────
    try:
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(pdf_bytes, dpi=200)
        result = []
        for page in pages:
            buf = _io.BytesIO()
            page.save(buf, format="PNG")
            result.append(buf.getvalue())
        logger.debug("pdf2image で PDF を %d ページ変換しました", len(result))
        return result
    except ImportError:
        pass  # pdf2image 未インストール
    except Exception as exc:
        logger.warning("pdf2image PDF 変換エラー: %s", exc)

    # ── フォールバック: pdfplumber でテキスト抽出のみ ──────────
    try:
        import pdfplumber
        with pdfplumber.open(_io.BytesIO(pdf_bytes)) as pdf:
            texts = [page.extract_text() or "" for page in pdf.pages]
        logger.warning("PDF→画像変換不可。テキスト抽出のみ実行します")
        # テキストを画像の代わりに返すことはできないため空リストで上流エラー処理へ
        return []
    except Exception:
        pass

    return []


# ── エンドポイント ────────────────────────────────────────────────────

@router.post("", summary="書類アップロード＋AI-OCR処理（末尾スラッシュなし）")
@router.post("/", summary="書類アップロード＋AI-OCR処理")
async def upload_and_process(
    file: UploadFile = File(...),
    client_id: str | None = Query(None, description="顧問先ID（UUIDまたは省略）"),
    auto_process: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """書類を 1 件アップロードして AI-OCR 処理する。

    処理後、信頼度に応じて自動で以下に分類されます:
    - **auto_confirmed**: 高精度 → 自動承認（確認不要）
    - **needs_review**: 中精度 → 確認画面に表示
    - **manual_input**: 低精度 → 手入力が必要
    """
    _validate_file(file)
    stored_name, file_path, file_size, _raw = await _save_file(file)
    mime = file.content_type or "application/octet-stream"

    # 顧問先UUID変換
    client_uuid = None
    if client_id:
        try:
            client_uuid = uuid.UUID(client_id)
        except ValueError:
            pass

    # ephemeral FS 対策: ファイルバイナリを base64 テキストとして DB に保存
    try:
        _file_content_b64: str | None = base64.b64encode(_raw).decode("ascii") if _raw else None
    except Exception as _enc_err:
        logger.warning("base64 encode 失敗: %s", _enc_err)
        _file_content_b64 = None

    doc = Document(
        original_filename=file.filename or stored_name,
        stored_filename=stored_name,
        file_path=file_path,
        file_size_bytes=file_size,
        mime_type=mime,
        status=DocStatus.UPLOADED,
        client_id=client_uuid,
        file_content=_file_content_b64,
    )
    db.add(doc)
    await db.flush()
    doc_id = doc.id

    if auto_process:
        await _process_document(doc_id, db, client_id=client_id)
        await db.refresh(doc)

    tier_msg = {
        "auto_confirmed": "✅ 高精度で自動承認されました",
        "needs_review":   "⚠️ OCR結果を確認してください",
        "manual_input":   "✏️ 手入力が必要です",
    }

    return {
        "document_id": str(doc_id),
        "filename": file.filename,
        "status": doc.status,
        "confidence_tier": doc.confidence_tier,
        "confidence_score": float(doc.confidence_score or 0),
        "arithmetic_ok": doc.arithmetic_check_ok,
        "review_flags": doc.review_flags or [],
        "message": tier_msg.get(doc.confidence_tier, "処理完了"),
    }


@router.post("/batch", summary="一括アップロード＋バックグラウンドOCR")
async def batch_upload(
    files: list[UploadFile] = File(...),
    client_id: str | None = Query(None),
    job_name: str = Query(""),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    """複数ファイルを一括アップロードしてバックグラウンドで処理する。

    月500枚以上の一括処理に対応。処理完了後に /upload/batch/{id}/status で確認。
    """
    if len(files) > 200:
        raise HTTPException(status_code=400, detail="一度に200ファイルまで")

    for f in files:
        _validate_file(f)

    client_uuid = None
    if client_id:
        try:
            client_uuid = uuid.UUID(client_id)
        except ValueError:
            pass

    job = BatchJob(
        job_name=job_name or f"一括OCR {len(files)}件",
        total_files=len(files),
        status="pending",
    )
    db.add(job)
    await db.flush()
    job_id = job.id

    doc_ids: list[uuid.UUID] = []
    for file in files:
        stored_name, file_path, file_size, _raw = await _save_file(file)
        try:
            _b64 = base64.b64encode(_raw).decode("ascii") if _raw else None
        except Exception:
            _b64 = None
        doc = Document(
            original_filename=file.filename or stored_name,
            stored_filename=stored_name,
            file_path=file_path,
            file_size_bytes=file_size,
            mime_type=file.content_type or "application/octet-stream",
            status=DocStatus.UPLOADED,
            batch_job_id=job_id,
            client_id=client_uuid,
            file_content=_b64,  # ephemeral FS 対策: base64 テキストで DB に保存
        )
        db.add(doc)
        await db.flush()
        doc_ids.append(doc.id)

    async def _run_batch():
        from src.db.database import AsyncSessionLocal
        from datetime import datetime as _dt
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select as _sel
            batch = (await session.execute(_sel(BatchJob).where(BatchJob.id == job_id))).scalar_one()
            batch.status = "running"
            batch.started_at = _dt.now()
            await session.flush()

            for did in doc_ids:
                try:
                    await _process_document(did, session, client_id=client_id)
                    batch.processed_files += 1
                except Exception as exc:
                    logger.error("バッチ処理エラー doc=%s: %s", did, exc)
                    batch.failed_files += 1
                await session.flush()

            batch.status = "completed"
            batch.completed_at = _dt.now()
            await session.commit()

    background_tasks.add_task(_run_batch)

    return {
        "batch_job_id": str(job_id),
        "total_files": len(files),
        "message": f"{len(files)} 件を受け付けました。バックグラウンドで処理中です。",
    }


@router.get("/batch/{job_id}/status", summary="バッチ進捗確認")
async def get_batch_status(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    job = (await db.execute(select(BatchJob).where(BatchJob.id == job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    progress = int(job.processed_files / max(job.total_files, 1) * 100)
    return {
        "job_id": str(job_id),
        "job_name": job.job_name,
        "status": job.status,
        "total_files": job.total_files,
        "processed_files": job.processed_files,
        "failed_files": job.failed_files,
        "progress_percent": progress,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


@router.post("/{doc_id}/reprocess", summary="再OCR処理")
async def reprocess_document(
    doc_id: uuid.UUID,
    client_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="書類が見つかりません")
    if not doc.file_content and not Path(doc.file_path).exists():
        raise HTTPException(
            status_code=400,
            detail="原本ファイルが見つかりません。再アップロードしてください。",
        )
    await _process_document(
        doc_id,
        db,
        client_id=client_id or (str(doc.client_id) if doc.client_id else None),
    )
    await db.refresh(doc)
    if doc.processing_error:
        raise HTTPException(
            status_code=422,
            detail=f"再OCR処理に失敗しました: {doc.processing_error}",
        )
    return {
        "message": "再処理完了",
        "document_id": str(doc_id),
        "status": doc.status,
        "confidence_tier": doc.confidence_tier,
    }
