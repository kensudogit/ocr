"""OpenAI による OCR 後処理補正。

Azure Document Intelligence / OCR テキストと
初期抽出結果を入力し、仕訳フィールドを補正・正規化する。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

from src.config import settings
from src.core.practice_profile import openai_context_for_doc_type
from src.core.extractor import ExtractedFields
from src.core.vlm_extractor import VlmExtractor

logger = logging.getLogger(__name__)

_CORRECTION_SYSTEM_BASE = """\
あなたは日本の地方中規模税理士事務所（記帳代行・月500枚以上）向け OCR 後処理 AI です。
OCR 全文テキストと機械抽出された初期値を照合し、正確な仕訳 JSON を出力してください。

共通ルール:
- 金額は数値のみ（カンマ・¥ 不要）
- 日付は YYYY-MM-DD（和暦は西暦に変換）
- 適格請求書番号は T + 13桁（14文字）
- OCR テキストに根拠がない値は null（推測しない）
- 合計 = 税抜 + 税 の整合性を確認し、矛盾があれば OCR テキストを優先
- 顧問先の機密情報 — テキストにない口座番号・個人番号を捏造しない
- JSON のみ返答

出力フィールド:
transaction_date, vendor_name, vendor_address, vendor_phone,
vendor_registration_no, total_amount, subtotal_amount,
tax_amount_10, tax_amount_8, invoice_number, payment_method,
doc_type, account_title_suggestion, tax_category_suggestion,
note, line_items, confidence_hint, correction_notes
"""


def _build_system_prompt(doc_type: str | None) -> str:
    ctx = openai_context_for_doc_type(doc_type)
    return f"{_CORRECTION_SYSTEM_BASE}\n\n書類種別ヒント: {ctx}"


@dataclass
class PostProcessResult:
    """OpenAI 後処理結果。"""

    fields: ExtractedFields
    raw_json: dict
    model_used: str
    processing_time_ms: float
    correction_notes: str | None = None


class OpenAiPostProcessor:
    """OpenAI テキストベース後処理。"""

    def __init__(self) -> None:
        self._client = None
        self._initialized = False

    @property
    def configured(self) -> bool:
        return bool(settings.openai_api_key)

    def _get_client(self):
        if self._initialized:
            return self._client
        self._initialized = True
        if not settings.openai_api_key:
            return None
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=settings.openai_api_key)
        except Exception as exc:
            logger.error("OpenAI 後処理クライアント初期化失敗: %s", exc)
        return self._client

    async def refine(
        self,
        ocr_text: str,
        draft: dict,
        doc_type: str | None = None,
    ) -> PostProcessResult | None:
        """OCR テキストと初期抽出 dict を OpenAI で補正。"""
        client = self._get_client()
        if client is None or not ocr_text.strip():
            return None

        start = time.perf_counter()
        user_content = json.dumps(
            {
                "ocr_text": ocr_text[:12000],
                "draft_extraction": draft,
            },
            ensure_ascii=False,
            indent=2,
        )

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=settings.openai_postprocess_model,
                    messages=[
                        {"role": "system", "content": _build_system_prompt(doc_type)},
                        {
                            "role": "user",
                            "content": (
                                "以下の OCR 結果を補正してください:\n\n"
                                + user_content
                            ),
                        },
                    ],
                    max_tokens=2500,
                    temperature=0,
                    response_format={"type": "json_object"},
                ),
            )
            raw_text = response.choices[0].message.content or "{}"
            raw_json = json.loads(raw_text)
            vlm = VlmExtractor()
            parsed = vlm._parse_vlm_response(  # noqa: SLF001
                raw_text, settings.openai_postprocess_model, start
            )
            fields = parsed.fields
            elapsed = (time.perf_counter() - start) * 1000
            return PostProcessResult(
                fields=fields,
                raw_json=raw_json,
                model_used=settings.openai_postprocess_model,
                processing_time_ms=elapsed,
                correction_notes=raw_json.get("correction_notes"),
            )
        except Exception as exc:
            logger.error("OpenAI 後処理エラー: %s", exc)
            return None
