"""VLM（Vision Language Model）ベースの構造化抽出エンジン。

OCR テキストを経由せず、画像を直接 VLM に投げて
仕訳フィールドを JSON 構造で抽出する。

対応モデル:
  - OpenAI  GPT-4o / GPT-4o-mini （推奨）
  - Google  Gemini 2.0 Flash
  - フォールバック: 既存 PaddleOCR + extractor

VLM が使えない場合は自動フォールバック。
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from src.config import settings
from src.core.extractor import DataExtractor, ExtractedFields

logger = logging.getLogger(__name__)

# ── プロンプト ────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
あなたは日本の税理士事務所向け書類読取AIです。
入力画像から以下のフィールドをJSON形式で正確に抽出してください。

必須フィールド:
- transaction_date: 取引日 (YYYY-MM-DD形式。不明なら null)
- vendor_name: 取引先名・店舗名 (文字列)
- total_amount: 合計金額・税込合計 (数値のみ。¥マーク不要)
- subtotal_amount: 税抜金額・本体価格 (数値のみ。不明なら null)
- tax_amount_10: 消費税額(10%分) (数値のみ。不明なら null)
- tax_amount_8: 消費税額(8%軽減税率分) (数値のみ。不明なら null)
- vendor_registration_no: 適格請求書発行事業者登録番号 (T + 13桁。例: T1234567890123。ない場合は null)
- invoice_number: 請求書番号・伝票番号 (文字列。ない場合は null)
- payment_method: 支払方法 (「現金」「クレジットカード」「電子マネー」「銀行振込」のいずれか。不明なら null)
- doc_type: 書類種別 (「receipt」「handwritten」「invoice」「card_statement」のいずれか)
- vendor_address: 住所 (不明なら null)
- vendor_phone: 電話番号 (不明なら null)
- account_title_suggestion: 勘定科目の提案 (「消耗品費」「旅費交通費」「交際費」「通信費」「会議費」「水道光熱費」など。不明なら null)
- tax_category_suggestion: 税区分の提案 (「課税仕入10%」「課税仕入8%軽減」「非課税」「不課税」のいずれか)
- note: 特記事項・但し書き (文字列。ない場合は null)
- line_items: 明細行リスト (各要素: {description, quantity, unit_price, amount, tax_rate})
- confidence_hint: 抽出の確信度 (0.0〜1.0)
- ocr_issues: 読み取り困難な箇所のメモ (文字列。問題なければ null)

重要事項:
- 金額は数値のみ（カンマ・¥マーク不要）
- 日付は必ずYYYY-MM-DD形式に変換（令和→西暦変換必須。例: 令和6年3月15日→2024-03-15）
- 適格請求書番号は必ずTから始まる14文字
- 読み取れないフィールドは null（推測しない）
- JSONのみ返答（説明文不要）
"""

_USER_PROMPT = "この書類の仕訳データをJSONで抽出してください。"


@dataclass
class VlmExtractionResult:
    """VLM 抽出結果。"""
    fields: ExtractedFields
    raw_json: dict
    model_used: str
    processing_time_ms: float
    confidence_hint: float = 0.0
    ocr_issues: str | None = None
    fallback_used: bool = False


class VlmExtractor:
    """VLM ベースの書類構造化抽出クラス。

    使い方:
        vlm = VlmExtractor()
        result = await vlm.extract(pil_image)
        fields = result.fields
    """

    def __init__(self) -> None:
        self._openai_client = None
        self._gemini_client = None
        self._openai_initialized = False
        self._gemini_initialized = False
        self._fallback_extractor = DataExtractor()

    # ──────────────────────────────────────────────────────────────
    # パブリック API
    # ──────────────────────────────────────────────────────────────

    async def extract(
        self,
        image: Image.Image | np.ndarray,
        client_id: str | None = None,
        doc_type_hint: str | None = None,
    ) -> VlmExtractionResult:
        """画像から仕訳データを VLM で抽出する。

        VLM が利用できない場合は従来の OCR + 正規表現抽出にフォールバック。
        """
        start = time.perf_counter()
        pil = self._to_pil(image)
        img_b64 = self._image_to_base64(pil)

        # モデル優先順位: OpenAI → Gemini → フォールバック
        result: VlmExtractionResult | None = None

        if settings.openai_api_key:
            result = await self._extract_openai(img_b64, start)

        if result is None and settings.gemini_api_key:
            result = await self._extract_gemini(pil, start)

        if result is None:
            logger.warning("VLM が利用できません。OCR フォールバックを使用します")
            result = await self._extract_fallback(pil, start)

        elapsed = (time.perf_counter() - start) * 1000
        result.processing_time_ms = elapsed
        return result

    # ──────────────────────────────────────────────────────────────
    # OpenAI GPT-4o
    # ──────────────────────────────────────────────────────────────

    async def _extract_openai(self, img_b64: str, start: float) -> VlmExtractionResult | None:
        """GPT-4o で抽出する。"""
        client = self._get_openai_client()
        if client is None:
            return None

        import asyncio
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=settings.openai_model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{img_b64}",
                                        "detail": "high",
                                    },
                                },
                                {"type": "text", "text": _USER_PROMPT},
                            ],
                        },
                    ],
                    max_tokens=2000,
                    temperature=0,
                    response_format={"type": "json_object"},
                ),
            )
            raw_text = response.choices[0].message.content or "{}"
            return self._parse_vlm_response(raw_text, model=settings.openai_model, start=start)
        except Exception as exc:
            logger.error("OpenAI API エラー: %s", exc)
            return None

    def _get_openai_client(self):
        if self._openai_initialized:
            return self._openai_client
        self._openai_initialized = True
        if not settings.openai_api_key:
            return None
        try:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=settings.openai_api_key)
            logger.info("OpenAI クライアント初期化完了（モデル: %s）", settings.openai_model)
        except ImportError:
            logger.warning("openai パッケージが見つかりません: pip install openai")
        except Exception as exc:
            logger.error("OpenAI 初期化エラー: %s", exc)
        return self._openai_client

    # ──────────────────────────────────────────────────────────────
    # Google Gemini Vision
    # ──────────────────────────────────────────────────────────────

    async def _extract_gemini(self, pil: Image.Image, start: float) -> VlmExtractionResult | None:
        """Gemini 2.0 Flash で抽出する。"""
        if not self._get_gemini_client():
            return None
        import asyncio
        try:
            import google.generativeai as genai
            model = genai.GenerativeModel(settings.gemini_model)
            prompt = f"{_SYSTEM_PROMPT}\n\n{_USER_PROMPT}"
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: model.generate_content([prompt, pil]),
            )
            raw_text = response.text or "{}"
            # Gemini は json オブジェクトのみを返すとは限らないので抽出
            json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if json_match:
                raw_text = json_match.group(0)
            return self._parse_vlm_response(raw_text, model=settings.gemini_model, start=start)
        except Exception as exc:
            logger.error("Gemini API エラー: %s", exc)
            return None

    def _get_gemini_client(self):
        if self._gemini_initialized:
            return self._gemini_client
        self._gemini_initialized = True
        if not settings.gemini_api_key:
            return None
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.gemini_api_key)
            self._gemini_client = genai  # モジュール自体を保持
            logger.info("Gemini クライアント初期化完了（モデル: %s）", settings.gemini_model)
        except ImportError:
            logger.warning("google-generativeai が見つかりません: pip install google-generativeai")
        except Exception as exc:
            logger.error("Gemini 初期化エラー: %s", exc)
        return self._gemini_client

    # ──────────────────────────────────────────────────────────────
    # フォールバック（従来の OCR + 正規表現）
    # ──────────────────────────────────────────────────────────────

    async def _extract_fallback(self, pil: Image.Image, start: float) -> VlmExtractionResult:
        """PaddleOCR + 正規表現抽出にフォールバックする。"""
        from src.core.ocr_engine import OcrEngine
        from src.core.preprocessor import ImagePreprocessor
        import numpy as np

        preprocessor = ImagePreprocessor()
        img_array = np.array(pil)
        prep = preprocessor.process(img_array)
        ocr = OcrEngine()
        ocr_result = await ocr.recognize(prep.pil_image)
        fields = self._fallback_extractor.extract(ocr_result.full_text)

        return VlmExtractionResult(
            fields=fields,
            raw_json={},
            model_used="paddle_fallback",
            processing_time_ms=(time.perf_counter() - start) * 1000,
            confidence_hint=ocr_result.overall_confidence,
            fallback_used=True,
        )

    # ──────────────────────────────────────────────────────────────
    # レスポンス変換
    # ──────────────────────────────────────────────────────────────

    def _parse_vlm_response(
        self, raw_text: str, model: str, start: float
    ) -> VlmExtractionResult:
        """VLM の JSON レスポンスを ExtractedFields に変換する。"""
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.warning("VLM JSON パースエラー: %.200s", raw_text)
            data = {}

        fields = ExtractedFields()

        # ── 日付 ──
        if d := data.get("transaction_date"):
            try:
                from datetime import datetime
                fields.transaction_date = datetime.fromisoformat(str(d))
            except Exception:
                pass

        # ── 文字列フィールド ──
        fields.vendor_name             = _s(data.get("vendor_name"))
        fields.vendor_address          = _s(data.get("vendor_address"))
        fields.vendor_phone            = _s(data.get("vendor_phone"))
        fields.vendor_registration_no  = _s(data.get("vendor_registration_no"))
        fields.invoice_number          = _s(data.get("invoice_number"))
        fields.payment_method          = _s(data.get("payment_method"))
        fields.note                    = _s(data.get("note"))
        fields.account_title           = _s(data.get("account_title_suggestion"))

        # ── 金額 ──
        fields.total_amount     = _f(data.get("total_amount"))
        fields.subtotal_amount  = _f(data.get("subtotal_amount"))
        fields.tax_amount_10    = _f(data.get("tax_amount_10"))
        fields.tax_amount_8     = _f(data.get("tax_amount_8"))

        # ── 明細行 ──
        fields.line_items = [
            {
                "description": item.get("description"),
                "quantity":    item.get("quantity"),
                "unit_price":  _f(item.get("unit_price")),
                "amount":      _f(item.get("amount")),
                "tax_rate":    _f(item.get("tax_rate")),
            }
            for item in (data.get("line_items") or [])
            if isinstance(item, dict)
        ]

        # ── 信頼度 ──
        confidence_hint = float(data.get("confidence_hint") or 0.8)

        return VlmExtractionResult(
            fields=fields,
            raw_json=data,
            model_used=model,
            processing_time_ms=(time.perf_counter() - start) * 1000,
            confidence_hint=confidence_hint,
            ocr_issues=_s(data.get("ocr_issues")),
            fallback_used=False,
        )

    # ──────────────────────────────────────────────────────────────
    # ユーティリティ
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _to_pil(image: Image.Image | np.ndarray) -> Image.Image:
        if isinstance(image, np.ndarray):
            return Image.fromarray(image).convert("RGB")
        return image.convert("RGB")

    @staticmethod
    def _image_to_base64(pil: Image.Image, max_px: int = 2048) -> str:
        """画像を base64 エンコードする（長辺 max_px にリサイズ）。"""
        w, h = pil.size
        if max(w, h) > max_px:
            scale = max_px / max(w, h)
            pil = pil.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        pil.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode()


# ── ユーティリティ関数 ─────────────────────────────────────────────────

def _s(v) -> str | None:
    """None または空文字列を None に正規化。"""
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() != "null" else None


def _f(v) -> float | None:
    """数値変換。失敗したら None。"""
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "").replace("¥", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None
