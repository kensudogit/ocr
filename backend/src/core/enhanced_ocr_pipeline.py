"""OpenCV + Azure Document Intelligence + OpenAI 後処理の統合 OCR パイプライン。

処理フロー:
  1. OpenCV 前処理（傾き補正・CLAHE・適応的二値化）
  2. Azure Document Intelligence で OCR + 構造化抽出
  3. OpenAI で OCR テキストと初期値を照合・補正
  4. 失敗時は VLM（GPT-4o Vision）にフォールバック
"""
from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass, field

from PIL import Image

from src.config import settings
from src.core.azure_document_intelligence import (
    AzureDocumentIntelligenceClient,
    AzureDiResult,
    map_to_extracted_dict,
    normalize_registration_no,
    parse_date_value,
)
from src.core.practice_profile import estimate_doc_type_from_image
from src.core.extractor import DataExtractor, ExtractedFields
from src.core.openai_postprocessor import OpenAiPostProcessor
from src.core.opencv_preprocessor import OpenCvPreprocessor, opencv_available
from src.core.preprocessor import ImagePreprocessor, PreprocessResult
from src.core.vlm_extractor import VlmExtractionResult, VlmExtractor

logger = logging.getLogger(__name__)


@dataclass
class EnhancedOcrResult:
    """統合 OCR パイプライン結果（VlmExtractionResult 互換）。"""

    fields: ExtractedFields
    raw_json: dict
    model_used: str
    processing_time_ms: float = 0.0
    confidence_hint: float = 0.0
    ocr_issues: str | None = None
    fallback_used: bool = False
    ocr_raw_text: str = ""
    pipeline_steps: list[str] = field(default_factory=list)
    preprocessing: PreprocessResult | None = None


class EnhancedOcrPipeline:
    """認識率向上パイプライン。"""

    def __init__(self) -> None:
        self._opencv = OpenCvPreprocessor()
        self._pil = ImagePreprocessor(
            enhance_thermal=settings.enhance_thermal_paper,
            auto_rotate=settings.auto_rotate,
            denoise_level=settings.denoise_level,
        )
        self._azure = AzureDocumentIntelligenceClient()
        self._postprocessor = OpenAiPostProcessor()
        self._vlm = VlmExtractor()
        self._extractor = DataExtractor()

    @property
    def enabled(self) -> bool:
        mode = settings.ocr_pipeline_mode
        if mode == "vlm":
            return False
        if mode == "azure_openai":
            return self._azure.configured
        # hybrid: Azure または OpenCV+OpenAI のいずれか
        return (
            self._azure.configured
            or (opencv_available() and self._postprocessor.configured)
        )

    async def extract(
        self,
        image_bytes: bytes,
        doc_type_hint: str | None = None,
        client_id: str | None = None,
    ) -> EnhancedOcrResult:
        """画像から仕訳データを抽出する。"""
        start = time.perf_counter()
        steps: list[str] = []

        # ── Step 1: OpenCV 前処理 ───────────────────────────────
        if settings.use_opencv_preprocess and opencv_available():
            prep = self._opencv.process(image_bytes, doc_type_hint)
            steps.append("opencv_preprocess")
        else:
            prep = self._pil.process(image_bytes, doc_type_hint)
            steps.append("pil_preprocess")

        # 書類種別推定（画像特徴 + 呼び出し元ヒント）
        effective_doc_type = doc_type_hint
        if not effective_doc_type:
            estimated, est_conf = estimate_doc_type_from_image(prep)
            if est_conf >= 0.35:
                effective_doc_type = estimated
                steps.append(f"doc_type_estimated:{estimated}")

        # 前処理済み PNG バイト（Azure 送信用）
        buf = io.BytesIO()
        prep.pil_image.save(buf, format="PNG")
        processed_bytes = buf.getvalue()

        azure_result: AzureDiResult | None = None
        draft: dict = {}
        ocr_text = ""

        # ── Step 2: Azure Document Intelligence ─────────────────
        if self._azure.configured and settings.ocr_pipeline_mode in (
            "azure_openai",
            "hybrid",
        ):
            azure_result = await self._azure.analyze(
                processed_bytes,
                content_type="image/png",
                doc_type_hint=effective_doc_type,
            )
            if azure_result:
                steps.append(f"azure_di:{azure_result.model_id}")
                ocr_text = azure_result.content
                draft = map_to_extracted_dict(azure_result)
                if azure_result.confidence:
                    draft["confidence_hint"] = azure_result.confidence

        # Azure 未設定/失敗時: 前処理画像を VLM に直接渡す前段として空 draft
        if not ocr_text and not azure_result:
            steps.append("azure_di:skipped")

        # ── Step 3: OpenAI 後処理補正 ───────────────────────────
        if (
            self._postprocessor.configured
            and settings.use_openai_postprocess
            and ocr_text.strip()
        ):
            post = await self._postprocessor.refine(
                ocr_text, draft, doc_type=effective_doc_type
            )
            if post:
                steps.append(f"openai_postprocess:{post.model_used}")
                elapsed = (time.perf_counter() - start) * 1000
                raw = post.raw_json
                raw["ocr_engine"] = "opencv+azure+openai"
                raw["pipeline_steps"] = steps
                if effective_doc_type:
                    raw["doc_type"] = raw.get("doc_type") or effective_doc_type
                if post.correction_notes:
                    raw["correction_notes"] = post.correction_notes
                return EnhancedOcrResult(
                    fields=post.fields,
                    raw_json=raw,
                    model_used=f"azure+{post.model_used}",
                    processing_time_ms=elapsed,
                    confidence_hint=float(raw.get("confidence_hint") or 0.85),
                    ocr_issues=post.correction_notes,
                    ocr_raw_text=ocr_text,
                    pipeline_steps=steps,
                    preprocessing=prep,
                )

        # Azure のみ（OpenAI 後処理なし）— ルールベースマッピング
        if azure_result and ocr_text:
            steps.append("rule_mapping")
            fields = self._draft_to_fields(draft)
            if not fields.total_amount or not fields.vendor_name:
                ext = self._extractor.extract(ocr_text, effective_doc_type)
                fields = self._merge_fields(fields, ext)

            elapsed = (time.perf_counter() - start) * 1000
            if effective_doc_type:
                draft["doc_type"] = draft.get("doc_type") or effective_doc_type
            draft["pipeline_steps"] = steps
            return EnhancedOcrResult(
                fields=fields,
                raw_json=draft,
                model_used=f"azure_di:{azure_result.model_id}",
                processing_time_ms=elapsed,
                confidence_hint=azure_result.confidence,
                ocr_raw_text=ocr_text,
                pipeline_steps=steps,
                preprocessing=prep,
            )

        # ── Step 4: VLM フォールバック ───────────────────────────
        steps.append("vlm_fallback")
        vlm: VlmExtractionResult = await self._vlm.extract(
            prep.pil_image,
            client_id=client_id,
            doc_type_hint=effective_doc_type,
        )
        elapsed = (time.perf_counter() - start) * 1000
        raw = dict(vlm.raw_json)
        raw["pipeline_steps"] = steps
        raw["ocr_engine"] = "vlm_fallback"
        return EnhancedOcrResult(
            fields=vlm.fields,
            raw_json=raw,
            model_used=vlm.model_used,
            processing_time_ms=elapsed,
            confidence_hint=vlm.confidence_hint,
            ocr_issues=vlm.ocr_issues,
            fallback_used=True,
            ocr_raw_text=ocr_text or "",
            pipeline_steps=steps,
            preprocessing=prep,
        )

    @staticmethod
    def _draft_to_fields(draft: dict) -> ExtractedFields:
        fields = ExtractedFields()
        fields.transaction_date = parse_date_value(draft.get("transaction_date"))
        fields.vendor_name = draft.get("vendor_name")
        fields.vendor_address = draft.get("vendor_address")
        fields.vendor_registration_no = normalize_registration_no(
            draft.get("vendor_registration_no")
        )
        fields.invoice_number = draft.get("invoice_number")
        fields.total_amount = _to_float(draft.get("total_amount"))
        fields.subtotal_amount = _to_float(draft.get("subtotal_amount"))
        fields.tax_amount_10 = _to_float(draft.get("tax_amount_10"))
        fields.tax_amount_8 = _to_float(draft.get("tax_amount_8"))
        fields.account_title = draft.get("account_title_suggestion")
        fields.line_items = draft.get("line_items") or []
        return fields

    @staticmethod
    def _merge_fields(primary: ExtractedFields, secondary: ExtractedFields) -> ExtractedFields:
        """primary の空フィールドを secondary で補完。"""
        for attr in (
            "transaction_date", "vendor_name", "vendor_address", "vendor_phone",
            "vendor_registration_no", "total_amount", "subtotal_amount",
            "tax_amount_10", "tax_amount_8", "invoice_number", "payment_method",
            "note", "account_title",
        ):
            if getattr(primary, attr) is None:
                setattr(primary, attr, getattr(secondary, attr))
        if not primary.line_items and secondary.line_items:
            primary.line_items = secondary.line_items
        return primary


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("¥", "").strip())
    except (ValueError, TypeError):
        return None
