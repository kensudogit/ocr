"""Azure Document Intelligence（旧 Form Recognizer）OCR クライアント。

prebuilt-read / prebuilt-invoice / prebuilt-receipt モデルで
高精度 OCR と構造化フィールド抽出を行う。
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

API_VERSION = "2024-11-30"


@dataclass
class AzureDiResult:
    """Azure Document Intelligence 解析結果。"""

    content: str
    model_id: str
    fields: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    raw: dict = field(default_factory=dict)
    page_count: int = 1


class AzureDocumentIntelligenceClient:
    """Azure DI REST API クライアント。"""

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.endpoint = (endpoint or settings.azure_di_endpoint).rstrip("/")
        self.api_key = api_key or settings.azure_di_key

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.api_key)

    def _model_for_hint(self, doc_type_hint: str | None) -> str:
        if doc_type_hint in ("invoice",):
            return settings.azure_di_model_invoice
        if doc_type_hint in ("receipt", "handwritten"):
            return settings.azure_di_model_receipt
        if doc_type_hint in ("card_statement",):
            return settings.azure_di_model_card
        return settings.azure_di_model_default

    async def analyze(
        self,
        image_bytes: bytes,
        content_type: str = "image/png",
        doc_type_hint: str | None = None,
    ) -> AzureDiResult | None:
        """画像/PDF バイナリを Azure DI で解析する。"""
        if not self.configured:
            return None

        model_id = self._model_for_hint(doc_type_hint)
        url = (
            f"{self.endpoint}/documentintelligence/documentModels/"
            f"{model_id}:analyze?api-version={API_VERSION}"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": content_type,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, headers=headers, content=image_bytes)
                if resp.status_code not in (200, 202):
                    logger.error(
                        "Azure DI analyze 失敗 status=%s body=%s",
                        resp.status_code,
                        resp.text[:500],
                    )
                    return None

                op_url = resp.headers.get("Operation-Location")
                if not op_url:
                    # 同期レスポンス
                    data = resp.json()
                    return self._parse_result(data, model_id)

                # 非同期ポーリング
                for _ in range(60):
                    await asyncio.sleep(1.0)
                    poll = await client.get(
                        op_url,
                        headers={"Ocp-Apim-Subscription-Key": self.api_key},
                    )
                    if poll.status_code != 200:
                        continue
                    body = poll.json()
                    status = body.get("status")
                    if status == "succeeded":
                        return self._parse_result(body.get("analyzeResult", body), model_id)
                    if status == "failed":
                        logger.error("Azure DI 解析失敗: %s", body.get("error"))
                        return None
                logger.error("Azure DI ポーリングタイムアウト")
                return None
        except Exception as exc:
            logger.exception("Azure DI エラー: %s", exc)
            return None

    def _parse_result(self, data: dict, model_id: str) -> AzureDiResult:
        content = data.get("content") or ""
        fields: dict[str, Any] = {}
        confidences: list[float] = []

        for doc in data.get("documents") or []:
            for key, val in (doc.get("fields") or {}).items():
                parsed = self._parse_field_value(val)
                if parsed is not None:
                    fields[key] = parsed
                conf = val.get("confidence")
                if isinstance(conf, (int, float)):
                    confidences.append(float(conf))

        # paragraphs からもテキスト補完
        if not content:
            paras = [
                p.get("content", "")
                for p in data.get("paragraphs") or []
                if p.get("content")
            ]
            content = "\n".join(paras)

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.75
        pages = data.get("pages") or []
        return AzureDiResult(
            content=content,
            model_id=model_id,
            fields=fields,
            confidence=avg_conf,
            raw=data,
            page_count=max(1, len(pages)),
        )

    @staticmethod
    def _parse_field_value(field: dict) -> Any:
        if not field:
            return None
        ftype = field.get("type")
        if ftype == "string":
            return field.get("valueString") or field.get("content")
        if ftype == "number":
            return field.get("valueNumber")
        if ftype == "integer":
            return field.get("valueInteger")
        if ftype == "date":
            return field.get("valueDate")
        if ftype == "currency":
            cur = field.get("valueCurrency") or {}
            return cur.get("amount")
        if ftype == "array":
            items = []
            for item in field.get("valueArray") or []:
                if item.get("type") == "object":
                    obj = {}
                    for k, v in (item.get("valueObject") or {}).items():
                        obj[k] = AzureDocumentIntelligenceClient._parse_field_value(v)
                    items.append(obj)
            return items
        if ftype == "object":
            obj = {}
            for k, v in (field.get("valueObject") or {}).items():
                obj[k] = AzureDocumentIntelligenceClient._parse_field_value(v)
            return obj
        return field.get("content") or field.get("valueString")

    @staticmethod
    def map_to_extracted_dict(azure: AzureDiResult) -> dict[str, Any]:
        """Azure DI フィールドを VLM 互換 dict にマッピング。"""
        f = azure.fields
        result: dict[str, Any] = {
            "ocr_engine": f"azure_di:{azure.model_id}",
            "confidence_hint": azure.confidence,
        }

        # invoice / receipt 共通マッピング
        vendor = (
            f.get("VendorName")
            or f.get("MerchantName")
            or f.get("CustomerName")
        )
        result["vendor_name"] = vendor
        result["vendor_address"] = f.get("VendorAddress") or f.get("MerchantAddress")
        result["vendor_registration_no"] = (
            f.get("VendorTaxId") or f.get("TaxId") or f.get("VendorRegistrationNumber")
        )
        result["invoice_number"] = f.get("InvoiceId") or f.get("ReceiptNumber")
        result["total_amount"] = f.get("InvoiceTotal") or f.get("Total")
        result["subtotal_amount"] = f.get("SubTotal") or f.get("Subtotal")
        result["tax_amount_10"] = f.get("TotalTax") or f.get("Tax")

        tx_date = f.get("InvoiceDate") or f.get("TransactionDate") or f.get("DueDate")
        if isinstance(tx_date, str):
            result["transaction_date"] = tx_date
        elif tx_date:
            result["transaction_date"] = str(tx_date)

        # 明細
        items = f.get("Items") or []
        line_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            line_items.append({
                "description": item.get("Description") or item.get("ProductCode"),
                "quantity": item.get("Quantity"),
                "unit_price": item.get("UnitPrice") or item.get("Price"),
                "amount": item.get("Amount") or item.get("TotalPrice"),
                "tax_rate": item.get("TaxRate"),
            })
        result["line_items"] = line_items

        # OCR 全文があれば doc_type 推定
        text = azure.content.lower()
        if "請求" in azure.content or "invoice" in text:
            result["doc_type"] = "invoice"
        elif "カード" in azure.content or "利用明細" in azure.content:
            result["doc_type"] = "card_statement"
        elif "領収" in azure.content or "receipt" in text:
            result["doc_type"] = "receipt"
        else:
            result["doc_type"] = "unknown"

        return result


def parse_date_value(value: str | None) -> datetime | None:
    """日付文字列を datetime に変換。"""
    if not value:
        return None
    from dateutil import parser as date_parser

    try:
        return date_parser.parse(str(value))
    except (ValueError, TypeError):
        return None


def normalize_registration_no(value: str | None) -> str | None:
    if not value:
        return None
    m = re.search(r"T\d{13}", str(value).upper().replace(" ", ""))
    return m.group(0) if m else str(value).strip()
