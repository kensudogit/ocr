"""freee 公式 API 連携モジュール。

公式API を使用して仕訳（取引）を直接登録する。
freee API v1 / OAuth2 対応。

参照: https://developer.freee.co.jp/docs/accounting/reference
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.config import settings

if TYPE_CHECKING:
    from src.db.models import Document, ExtractedData

logger = logging.getLogger(__name__)


# ── 税区分コード マッピング ────────────────────────────────────────────
# freee の tax_code と UI 表示名のマッピング
_TAX_CODE_MAP: dict[str, int] = {
    "課税仕入10%":      17,   # 課税仕入 10%（軽減税率なし）
    "課税仕入8%軽減":   30,   # 課税仕入 8%（軽減税率）
    "非課税":           14,   # 非課税仕入
    "不課税":            0,   # 不課税
    "課税売上10%":      33,   # 課税売上 10%
}

# freee 勘定科目コード（デフォルト）
_ACCOUNT_CODE_MAP: dict[str, int] = {
    "消耗品費":    1012,
    "旅費交通費":  1013,
    "交際費":      1020,
    "通信費":      1011,
    "会議費":      1021,
    "水道光熱費":  1014,
    "新聞図書費":  1022,
    "福利厚生費":  1017,
    "外注費":      1018,
    "地代家賃":    1015,
    "修繕費":      1019,
    "雑費":        1025,
}


class FreeeApiClient:
    """freee 会計 API クライアント。

    認証:
      - アクセストークン直接指定（環境変数 FREEE_ACCESS_TOKEN）
      - OAuth2 認証コードフロー（本番は Web アプリ認証推奨）

    使い方:
        client = FreeeApiClient(access_token=token, company_id="12345")
        result = await client.create_deal(doc, ex)
    """

    BASE_URL = "https://api.freee.co.jp/api/1"
    TOKEN_URL = "https://accounts.freee.co.jp/public_api/token"
    AUTH_URL  = "https://accounts.freee.co.jp/oauth/authorize"

    def __init__(
        self,
        access_token: str | None = None,
        company_id: str | None = None,
    ) -> None:
        self.access_token = access_token or settings.freee_access_token
        self.company_id   = company_id   or settings.freee_company_id
        self._session = None

    # ──────────────────────────────────────────────────────────────
    # 認証
    # ──────────────────────────────────────────────────────────────

    @classmethod
    def get_auth_url(cls, redirect_uri: str, state: str = "") -> str:
        """OAuth2 認証 URL を生成する。"""
        params = {
            "client_id":     settings.freee_client_id,
            "redirect_uri":  redirect_uri,
            "response_type": "code",
            "state":         state,
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{cls.AUTH_URL}?{qs}"

    @classmethod
    async def exchange_code(cls, code: str, redirect_uri: str) -> dict:
        """認証コードをアクセストークンに交換する。"""
        import httpx
        async with httpx.AsyncClient() as client:
            r = await client.post(
                cls.TOKEN_URL,
                data={
                    "grant_type":    "authorization_code",
                    "client_id":     settings.freee_client_id,
                    "client_secret": settings.freee_client_secret,
                    "code":          code,
                    "redirect_uri":  redirect_uri,
                },
            )
            r.raise_for_status()
            return r.json()

    async def refresh_token(self, refresh_token: str) -> dict:
        """リフレッシュトークンでアクセストークンを更新する。"""
        import httpx
        async with httpx.AsyncClient() as client:
            r = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type":    "refresh_token",
                    "client_id":     settings.freee_client_id,
                    "client_secret": settings.freee_client_secret,
                    "refresh_token": refresh_token,
                },
            )
            r.raise_for_status()
            return r.json()

    # ──────────────────────────────────────────────────────────────
    # 取引（支出）登録
    # ──────────────────────────────────────────────────────────────

    async def create_deal(
        self,
        doc: "Document",
        ex: "ExtractedData",
    ) -> dict:
        """freee に取引（支出）を登録する。

        Returns:
            dict: freee API レスポンス（deal オブジェクト）
        """
        if not self.access_token or not self.company_id:
            raise ValueError("freee のアクセストークンまたは事業所IDが設定されていません")

        payload = self._build_deal_payload(doc, ex)
        return await self._post("/deals", payload)

    def _build_deal_payload(
        self,
        doc: "Document",
        ex: "ExtractedData",
    ) -> dict:
        """freee API 取引登録ペイロードを構築する。"""
        issue_date = (
            ex.transaction_date.strftime("%Y-%m-%d")
            if ex.transaction_date
            else datetime.now().strftime("%Y-%m-%d")
        )
        amount = int(ex.total_amount or 0)

        # 勘定科目コード
        account_id = _ACCOUNT_CODE_MAP.get(ex.account_title or "", 1012)

        # 税区分コード
        tax_code = _TAX_CODE_MAP.get(ex.tax_category or "課税仕入10%", 17)

        # 支払先（取引先）
        partner_name = ex.vendor_name or "不明"

        # 支払方法 → freee 口座タイプ
        account_item_id = self._payment_to_account(ex.payment_method)

        payload = {
            "company_id": int(self.company_id),
            "issue_date": issue_date,
            "type": "expense",               # 支出
            "due_date": issue_date,
            "amount": amount,
            "due_amount": amount,
            "payment_type": "expense",
            "details": [
                {
                    "tax_code":        tax_code,
                    "account_item_id": account_id,
                    "amount":          amount,
                    "description":     f"{partner_name} {doc.original_filename}"[:255],
                    "item_id":         None,
                    "section_id":      None,
                }
            ],
            "payments": [
                {
                    "amount":         amount,
                    "from_walletable_type": "account_item",
                    "from_walletable_id":   account_item_id,
                    "date":           issue_date,
                }
            ],
            "receipt_ids": [],
        }

        # 適格請求書番号があれば追加
        if ex.vendor_registration_no:
            payload["qualified_invoice_status"] = "qualified"

        return payload

    @staticmethod
    def _payment_to_account(payment_method: str | None) -> int:
        """支払方法を freee の口座IDに変換する（デフォルト値）。"""
        # 実際の運用では freee の口座ID を設定する
        defaults = {
            "現金":         1,    # 現金
            "クレジットカード": 2, # クレジットカード（未払金）
            "銀行振込":     3,    # 普通預金
            "口座引落":     3,
            "電子マネー":   1,
        }
        return defaults.get(payment_method or "", 1)

    # ──────────────────────────────────────────────────────────────
    # 取引先・勘定科目取得
    # ──────────────────────────────────────────────────────────────

    async def get_partners(self) -> list[dict]:
        """取引先一覧を取得する。"""
        return await self._get(f"/partners?company_id={self.company_id}")

    async def get_account_items(self) -> list[dict]:
        """勘定科目一覧を取得する。"""
        return await self._get(f"/account_items?company_id={self.company_id}")

    # ──────────────────────────────────────────────────────────────
    # HTTP ユーティリティ
    # ──────────────────────────────────────────────────────────────

    async def _post(self, path: str, payload: dict) -> dict:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.BASE_URL}{path}",
                json=payload,
                headers=self._headers(),
            )
            if not r.is_success:
                logger.error("freee API エラー %s: %s", r.status_code, r.text)
                r.raise_for_status()
            return r.json()

    async def _get(self, path: str) -> list | dict:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{self.BASE_URL}{path}",
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type":  "application/json",
            "X-Api-Version": "2020-06-15",
        }
