"""書類 CRUD API エンドポイント。"""
from __future__ import annotations

import uuid
from datetime import datetime

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.rule_engine import get_rule_engine
from src.db.database import get_db
from src.db.models import BatchJob, DocStatus, Document, ExtractedData, JournalHistory, LineItem

router = APIRouter(prefix="/documents", tags=["documents"])
_rule_engine = get_rule_engine()


# ── スキーマ ─────────────────────────────────────────────────────────

class ExtractedDataUpdate(BaseModel):
    """抽出データの更新（確認・修正）スキーマ。"""
    transaction_date: datetime | None = None
    vendor_name: str | None = None
    vendor_address: str | None = None
    vendor_phone: str | None = None
    vendor_registration_no: str | None = None
    total_amount: float | None = None
    subtotal_amount: float | None = None
    tax_amount_10: float | None = None
    tax_amount_8: float | None = None
    invoice_number: str | None = None
    payment_method: str | None = None
    account_title: str | None = None
    tax_category: str | None = None
    cost_center: str | None = None
    note: str | None = None


class DocumentListResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    doc_type: str
    status: str
    ocr_confidence: float | None
    uploaded_at: datetime
    processed_at: datetime | None
    approved_at: datetime | None
    total_amount: float | None
    vendor_name: str | None
    transaction_date: datetime | None

    class Config:
        from_attributes = True


# ── エンドポイント ────────────────────────────────────────────────────

@router.get("", summary="書類一覧取得（末尾スラッシュなし）")
@router.get("/", summary="書類一覧取得")
async def list_documents(
    status: str | None = Query(None, description="フィルタ: uploaded/pending/approved等"),
    doc_type: str | None = Query(None, description="フィルタ: receipt/invoice等"),
    confidence_tier: str | None = Query(None, description="フィルタ: needs_review/auto_confirmed/manual_input"),
    client_id: str | None = Query(None, description="顧問先IDでフィルタ"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """書類一覧を取得する。ページネーション対応。"""
    stmt = (
        select(Document)
        .options(selectinload(Document.extracted))
        .order_by(Document.uploaded_at.desc())
    )
    if status:
        stmt = stmt.where(Document.status == status)
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if confidence_tier:
        stmt = stmt.where(Document.confidence_tier == confidence_tier)
    if client_id:
        try:
            stmt = stmt.where(Document.client_id == uuid.UUID(client_id))
        except ValueError:
            pass

    # 総件数
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # ページネーション
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    docs = (await db.execute(stmt)).scalars().all()

    items = []
    for doc in docs:
        ex = doc.extracted
        items.append({
            "id": doc.id,
            "original_filename": doc.original_filename,
            "doc_type": doc.doc_type,
            "status": doc.status,
            "ocr_confidence": doc.ocr_confidence,
            "uploaded_at": doc.uploaded_at,
            "processed_at": doc.processed_at,
            "approved_at": doc.approved_at,
            "total_amount": float(ex.total_amount) if ex and ex.total_amount else None,
            "vendor_name": ex.vendor_name if ex else None,
            "transaction_date": ex.transaction_date if ex else None,
            "confidence_tier": doc.confidence_tier,
            "confidence_score": float(doc.confidence_score) if doc.confidence_score else None,
            "arithmetic_check_ok": doc.arithmetic_check_ok,
            "review_flags": doc.review_flags or [],
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.get("/{doc_id}", summary="書類詳細取得")
async def get_document(doc_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """書類の詳細情報を取得する（OCR テキスト・抽出データ・明細含む）。"""
    stmt = (
        select(Document)
        .options(
            selectinload(Document.extracted),
            selectinload(Document.line_items),
            selectinload(Document.export_logs),
        )
        .where(Document.id == doc_id)
    )
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="書類が見つかりません")

    ex = doc.extracted
    return {
        "id": doc.id,
        "original_filename": doc.original_filename,
        "file_path": doc.file_path,
        "doc_type": doc.doc_type,
        "doc_type_confidence": doc.doc_type_confidence,
        "status": doc.status,
        "ocr_engine_used": doc.ocr_engine_used,
        "ocr_confidence": doc.ocr_confidence,
        "ocr_raw_text": doc.ocr_raw_text,
        "preprocessing_applied": doc.preprocessing_applied,
        "uploaded_at": doc.uploaded_at,
        "processed_at": doc.processed_at,
        "approved_at": doc.approved_at,
        "approved_by": doc.approved_by,
        "extracted": {
            "transaction_date": ex.transaction_date if ex else None,
            "vendor_name": ex.vendor_name if ex else None,
            "vendor_address": ex.vendor_address if ex else None,
            "vendor_phone": ex.vendor_phone if ex else None,
            "vendor_registration_no": ex.vendor_registration_no if ex else None,
            "total_amount": float(ex.total_amount) if ex and ex.total_amount else None,
            "subtotal_amount": float(ex.subtotal_amount) if ex and ex.subtotal_amount else None,
            "tax_amount_10": float(ex.tax_amount_10) if ex and ex.tax_amount_10 else None,
            "tax_amount_8": float(ex.tax_amount_8) if ex and ex.tax_amount_8 else None,
            "invoice_number": ex.invoice_number if ex else None,
            "payment_method": ex.payment_method if ex else None,
            "account_title": ex.account_title if ex else None,
            "tax_category": ex.tax_category if ex else None,
            "cost_center": ex.cost_center if ex else None,
            "note": ex.note if ex else None,
            "confidence_scores": ex.confidence_scores if ex else None,
            "is_manually_corrected": ex.is_manually_corrected if ex else False,
        } if ex else None,
        "line_items": [
            {
                "id": li.id,
                "sort_order": li.sort_order,
                "description": li.description,
                "quantity": float(li.quantity) if li.quantity else None,
                "unit": li.unit,
                "unit_price": float(li.unit_price) if li.unit_price else None,
                "amount": float(li.amount) if li.amount else None,
                "tax_rate": float(li.tax_rate) if li.tax_rate else None,
                "account_title": li.account_title,
            }
            for li in doc.line_items
        ],
        "export_logs": [
            {
                "id": log.id,
                "export_format": log.export_format,
                "exported_at": log.exported_at,
                "row_count": log.row_count,
            }
            for log in doc.export_logs
        ],
    }


@router.put("/{doc_id}/extracted", summary="抽出データを更新（手動修正）")
async def update_extracted(
    doc_id: uuid.UUID,
    body: ExtractedDataUpdate,
    corrected_by: str = Query("staff", description="修正担当者名"),
    db: AsyncSession = Depends(get_db),
):
    """担当者が OCR 抽出結果を手動修正する。"""
    stmt = select(Document).options(selectinload(Document.extracted)).where(Document.id == doc_id)
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="書類が見つかりません")

    if not doc.extracted:
        ex = ExtractedData(document_id=doc_id)
        db.add(ex)
        doc.extracted = ex
    else:
        ex = doc.extracted

    # 変更があったフィールドのみ更新
    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(ex, field, value)

    ex.is_manually_corrected = True

    # ステータスを確認待ちに戻す（修正後は再承認が必要）
    if doc.status == DocStatus.APPROVED:
        doc.status = DocStatus.PENDING

    await db.flush()
    return {"message": "抽出データを更新しました", "document_id": doc_id}


@router.post("/{doc_id}/approve", summary="書類を承認する")
async def approve_document(
    doc_id: uuid.UUID,
    approved_by: str = Query("staff", description="承認者名"),
    db: AsyncSession = Depends(get_db),
):
    """確認済みの書類を承認する。エクスポート対象になる。"""
    stmt = select(Document).options(selectinload(Document.extracted)).where(Document.id == doc_id)
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="書類が見つかりません")
    if doc.status not in (DocStatus.PENDING, DocStatus.UPLOADED):
        raise HTTPException(
            status_code=400,
            detail=f"この書類は承認できない状態です: {doc.status}",
        )

    doc.status = DocStatus.APPROVED
    doc.approved_at = datetime.now()
    doc.approved_by = approved_by
    if doc.extracted:
        doc.extracted.is_approved = True

    # ── ルールエンジンへの学習記録 ──────────────────────────────────
    ex = doc.extracted
    if ex and ex.vendor_name and ex.account_title:
        client_id = str(doc.client_id) if doc.client_id else None

        # メモリキャッシュに学習
        _rule_engine.learn(
            vendor_name=ex.vendor_name,
            account_title=ex.account_title,
            tax_category=ex.tax_category or "課税仕入10%",
            client_id=client_id,
        )

        # DB にも永続化（同一取引先の use_count を加算）
        existing = (
            await db.execute(
                select(JournalHistory).where(
                    JournalHistory.client_id == doc.client_id,
                    JournalHistory.vendor_name == ex.vendor_name,
                    JournalHistory.account_title == ex.account_title,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.use_count += 1
            existing.last_used_at = datetime.now()
        else:
            db.add(JournalHistory(
                client_id=doc.client_id,
                document_id=doc.id,
                vendor_name=ex.vendor_name,
                account_title=ex.account_title,
                tax_category=ex.tax_category or "課税仕入10%",
                payment_method=ex.payment_method,
            ))

    await db.flush()
    return {"message": "書類を承認しました", "document_id": doc_id}


@router.post("/{doc_id}/reject", summary="書類を差し戻す")
async def reject_document(
    doc_id: uuid.UUID,
    reason: str = Query("", description="差し戻し理由"),
    db: AsyncSession = Depends(get_db),
):
    """書類を差し戻す（再確認が必要）。"""
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="書類が見つかりません")
    doc.status = DocStatus.REJECTED
    if reason:
        doc.processing_error = f"差し戻し: {reason}"
    await db.flush()
    return {"message": "書類を差し戻しました", "document_id": doc_id}


@router.get("/{doc_id}/file", summary="書類の原本画像を配信する")
async def get_document_file(doc_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """書類の原本ファイルバイナリを返す。

    優先順位:
      1. DB に保存された file_content バイナリ（Railway 対応）
      2. ローカルファイルシステムの file_path
    どちらも存在しない場合は 404。
    """
    doc = (await db.execute(
        select(Document).where(Document.id == doc_id)
    )).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="書類が見つかりません")

    mime = doc.mime_type or "application/octet-stream"

    # 1. DB バイナリ優先
    if doc.file_content:
        return Response(content=doc.file_content, media_type=mime)

    # 2. ローカルファイルシステムにフォールバック
    file_path = Path(doc.file_path) if doc.file_path else None
    if file_path and file_path.exists():
        return Response(content=file_path.read_bytes(), media_type=mime)

    raise HTTPException(
        status_code=404,
        detail="ファイルが見つかりません（コンテナ再起動後にアップロードし直してください）",
    )


@router.delete("/{doc_id}", summary="書類を削除する")
async def delete_document(doc_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """書類とその抽出データを削除する。"""
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="書類が見つかりません")
    await db.delete(doc)
    await db.flush()
    return {"message": "書類を削除しました"}


@router.get("/stats/summary", summary="統計サマリー")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """ダッシュボード用の統計情報を返す。"""
    status_counts = (
        await db.execute(
            select(Document.status, func.count(Document.id))
            .group_by(Document.status)
        )
    ).all()

    doc_type_counts = (
        await db.execute(
            select(Document.doc_type, func.count(Document.id))
            .group_by(Document.doc_type)
        )
    ).all()

    # 今月のアップロード数
    from datetime import date
    today = date.today()
    month_start = datetime(today.year, today.month, 1)
    monthly_count = (
        await db.execute(
            select(func.count(Document.id))
            .where(Document.uploaded_at >= month_start)
        )
    ).scalar_one()

    # 承認済みの合計金額
    total_approved = (
        await db.execute(
            select(func.sum(ExtractedData.total_amount))
            .join(Document)
            .where(Document.status == DocStatus.APPROVED)
        )
    ).scalar_one()

    return {
        "status_breakdown": {s: c for s, c in status_counts},
        "doc_type_breakdown": {t: c for t, c in doc_type_counts},
        "monthly_upload_count": monthly_count,
        "total_approved_amount": float(total_approved) if total_approved else 0.0,
    }
