"""共通仕訳データモデル（疎結合アーキテクチャ）。

設計方針:
  - 内部では「勘定科目の表示名（freee/MF/弥生に依存しない）」で保持
  - 出力直前に各ソフト専用アダプタ（AccountAdapter）が変換
  - 顧問先ごとの「名寄せマスタ」で各ソフトの正式名称にマッピング
  - freee は科目 ID（整数）、MF/弥生は完全一致テキストが必要

勘定科目マッピング例:
  内部名: "旅費交通費"
    → freee:  account_item_id = 1013
    → MF:     "旅費交通費"（マスタ登録名と完全一致）
    → 弥生:    "旅費交通費"（弥生マスタ名と完全一致）

顧問先固有の名寄せ例:
  client_id=A, vendor_name="東京都交通局"
    → 勘定科目: "旅費交通費"
    → 補助科目（MF）: "交通費_外出"
    → 部門（freee）: section_id=5
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal


# ── 勘定科目マスタ（内部標準名称 → 各ソフト固有情報） ─────────────────
# 実運用では DB テーブル（account_masters）で管理することを推奨
_INTERNAL_ACCOUNT_MASTER: dict[str, dict] = {
    # 内部名称: {freee_id, mf_name, yayoi_name, ...}
    "消耗品費":   {"freee_id": 1012, "mf": "消耗品費",   "yayoi": "消耗品費"},
    "旅費交通費": {"freee_id": 1013, "mf": "旅費交通費", "yayoi": "旅費交通費"},
    "交際費":     {"freee_id": 1020, "mf": "交際費",     "yayoi": "交際費"},
    "会議費":     {"freee_id": 1021, "mf": "会議費",     "yayoi": "会議費"},
    "通信費":     {"freee_id": 1011, "mf": "通信費",     "yayoi": "通信費"},
    "水道光熱費": {"freee_id": 1014, "mf": "水道光熱費", "yayoi": "水道光熱費"},
    "広告宣伝費": {"freee_id": 1009, "mf": "広告宣伝費", "yayoi": "広告宣伝費"},
    "新聞図書費": {"freee_id": 1022, "mf": "新聞図書費", "yayoi": "新聞図書費"},
    "福利厚生費": {"freee_id": 1017, "mf": "福利厚生費", "yayoi": "福利厚生費"},
    "外注費":     {"freee_id": 1018, "mf": "外注費",     "yayoi": "外注費"},
    "地代家賃":   {"freee_id": 1015, "mf": "地代家賃",   "yayoi": "地代家賃"},
    "修繕費":     {"freee_id": 1019, "mf": "修繕費",     "yayoi": "修繕費"},
    "雑費":       {"freee_id": 1025, "mf": "雑費",       "yayoi": "雑費"},
    "現金":       {"freee_id":    1, "mf": "現金",       "yayoi": "現金"},
    "未払金":     {"freee_id":  103, "mf": "未払金",     "yayoi": "未払金"},
    "普通預金":   {"freee_id":   10, "mf": "普通預金",   "yayoi": "普通預金"},
}

# ── 税区分マスタ ────────────────────────────────────────────────────
_TAX_MASTER: dict[str, dict] = {
    "課税仕入10%":   {"freee_code": 17, "mf": "課税仕入10%",  "yayoi": "10"},
    "課税仕入8%軽減": {"freee_code": 30, "mf": "課税仕入8%軽", "yayoi": "11"},
    "非課税":        {"freee_code": 14, "mf": "非課税仕入",    "yayoi": "14"},
    "不課税":        {"freee_code":  0, "mf": "対象外",        "yayoi": "0"},
}


@dataclass
class JournalLineItem:
    """仕訳明細行（共通内部形式）。"""
    description: str | None             # 摘要・品目
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal = Decimal("0")       # 税込金額
    tax_rate: Decimal = Decimal("0.10")  # 税率
    account_title: str | None = None     # 勘定科目（内部名称）
    tax_category: str = "課税仕入10%"    # 税区分（内部名称）


@dataclass
class JournalEntry:
    """共通仕訳エントリー（疎結合内部形式）。

    freee / MF / 弥生 のいずれにも依存しない内部表現。
    出力時に各 AccountAdapter が変換する。
    """
    # ── 識別 ──────────────────────────────────────────────────────
    document_id: str                         # 書類 UUID
    client_id: str | None = None             # 顧問先 ID

    # ── 基本仕訳データ ────────────────────────────────────────────
    transaction_date: datetime | None = None
    vendor_name: str | None = None
    vendor_address: str | None = None
    vendor_registration_no: str | None = None   # T+13桁（検証済み）
    invoice_number: str | None = None

    # ── 金額（Decimal で精度保証） ──────────────────────────────
    total_amount: Decimal = Decimal("0")
    subtotal_amount: Decimal | None = None
    tax_amount_10: Decimal | None = None
    tax_amount_8: Decimal | None = None

    # ── 勘定科目（内部標準名称） ──────────────────────────────────
    debit_account: str = "消耗品費"          # 借方勘定科目
    credit_account: str = "現金"             # 貸方勘定科目
    tax_category: str = "課税仕入10%"        # 税区分
    payment_method: str | None = None        # 支払方法

    # ── 補助情報 ──────────────────────────────────────────────────
    cost_center: str | None = None          # 部門
    project_code: str | None = None         # プロジェクト
    note: str | None = None                 # 摘要・備考

    # ── 明細行 ────────────────────────────────────────────────────
    line_items: list[JournalLineItem] = field(default_factory=list)

    # ── 電子帳簿保存法対応 ─────────────────────────────────────────
    original_image_hash: str | None = None  # 原本画像のSHA-256
    scan_timestamp: datetime | None = None  # スキャンタイムスタンプ
    scan_dpi: int | None = None             # スキャン解像度
    is_qualified_invoice: bool = False      # 適格請求書かどうか


# ── アダプタ基底クラス ──────────────────────────────────────────────────

class AccountAdapter:
    """勘定科目変換アダプタの基底クラス。

    各サブクラスが内部名称 → 各ソフト固有の形式に変換する。
    """

    def get_debit_account(self, entry: JournalEntry, client_master: dict | None = None) -> str | int:
        """借方勘定科目を取得する。"""
        raise NotImplementedError

    def get_credit_account(self, entry: JournalEntry, client_master: dict | None = None) -> str | int:
        """貸方勘定科目を取得する。"""
        raise NotImplementedError

    def get_tax_code(self, tax_category: str) -> str | int:
        """税区分コードを取得する。"""
        raise NotImplementedError

    def _resolve_account(
        self,
        internal_name: str,
        software_key: str,
        client_master: dict | None = None,
    ) -> str | int:
        """内部名称を各ソフト用の名称/IDに変換する。

        優先順位:
        1. 顧問先固有マスタ（client_master）
        2. システム標準マスタ（_INTERNAL_ACCOUNT_MASTER）
        3. 内部名称そのまま（フォールバック）
        """
        # 顧問先固有マスタを優先
        if client_master and internal_name in client_master:
            return client_master[internal_name].get(software_key, internal_name)

        # システム標準マスタ
        master = _INTERNAL_ACCOUNT_MASTER.get(internal_name)
        if master:
            return master.get(software_key, internal_name)

        return internal_name  # フォールバック


# ── freee アダプタ ─────────────────────────────────────────────────────

class FreeeAccountAdapter(AccountAdapter):
    """freee 会計向けアダプタ（科目IDを返す）。"""

    def get_debit_account(self, entry: JournalEntry, client_master: dict | None = None) -> int:
        """借方勘定科目の freee account_item_id を返す。"""
        result = self._resolve_account(entry.debit_account, "freee_id", client_master)
        return int(result) if str(result).isdigit() else 1012  # フォールバック: 消耗品費

    def get_credit_account(self, entry: JournalEntry, client_master: dict | None = None) -> int:
        result = self._resolve_account(entry.credit_account, "freee_id", client_master)
        return int(result) if str(result).isdigit() else 1  # フォールバック: 現金

    def get_tax_code(self, tax_category: str) -> int:
        """freee の tax_code（整数）を返す。"""
        tax = _TAX_MASTER.get(tax_category, {})
        return int(tax.get("freee_code", 17))


# ── マネーフォワード アダプタ ────────────────────────────────────────────

class MoneyForwardAccountAdapter(AccountAdapter):
    """マネーフォワード クラウド会計向けアダプタ（完全一致テキスト）。

    MF の CSV インポートは勘定科目のテキストが完全一致である必要がある。
    """

    def get_debit_account(self, entry: JournalEntry, client_master: dict | None = None) -> str:
        return str(self._resolve_account(entry.debit_account, "mf", client_master))

    def get_credit_account(self, entry: JournalEntry, client_master: dict | None = None) -> str:
        return str(self._resolve_account(entry.credit_account, "mf", client_master))

    def get_tax_code(self, tax_category: str) -> str:
        tax = _TAX_MASTER.get(tax_category, {})
        return str(tax.get("mf", "課税仕入10%"))


# ── 弥生会計 アダプタ ──────────────────────────────────────────────────

class YayoiAccountAdapter(AccountAdapter):
    """弥生会計向けアダプタ（完全一致テキスト + Shift-JIS 出力）。

    弥生の科目マスタに登録されている名称と完全一致させる必要がある。
    税区分コードは弥生独自の数値コード（0, 10, 11, 14...）。
    """

    def get_debit_account(self, entry: JournalEntry, client_master: dict | None = None) -> str:
        return str(self._resolve_account(entry.debit_account, "yayoi", client_master))

    def get_credit_account(self, entry: JournalEntry, client_master: dict | None = None) -> str:
        return str(self._resolve_account(entry.credit_account, "yayoi", client_master))

    def get_tax_code(self, tax_category: str) -> str:
        tax = _TAX_MASTER.get(tax_category, {})
        return str(tax.get("yayoi", "10"))


# ── アダプタファクトリ ─────────────────────────────────────────────────

def get_adapter(software: str) -> AccountAdapter:
    """会計ソフト名からアダプタを取得する。"""
    return {
        "freee":          FreeeAccountAdapter(),
        "money_forward":  MoneyForwardAccountAdapter(),
        "yayoi":          YayoiAccountAdapter(),
    }.get(software, MoneyForwardAccountAdapter())


# ── 顧問先固有マスタ管理 ──────────────────────────────────────────────

class ClientAccountMaster:
    """顧問先ごとの勘定科目名寄せマスタ。

    DB や JSON ファイルから読み込み、内部名称 → 各ソフト名称に変換する辞書を提供する。

    例（DB テーブル: client_account_masters）:
      client_id | internal_name | freee_id | mf_name    | yayoi_name
      A         | "旅費交通費"    | 1013    | "旅費交通費" | "旅費交通費"
      A         | "交通費"        | 1013    | "旅費交通費" | "旅費交通費"  ← 名寄せ
    """

    def __init__(self) -> None:
        # {client_id: {internal_name: {freee_id: X, mf: "...", yayoi: "..."}}}
        self._masters: dict[str, dict] = {}

    def load(self, client_id: str, mappings: list[dict]) -> None:
        """DB から取得したマッピングをロードする。

        Args:
            client_id: 顧問先 ID
            mappings: [{"internal_name": "...", "freee_id": ..., "mf": "...", "yayoi": "..."}]
        """
        self._masters[client_id] = {
            m["internal_name"]: {
                "freee_id": m.get("freee_id"),
                "mf":       m.get("mf_name"),
                "yayoi":    m.get("yayoi_name"),
            }
            for m in mappings
            if m.get("internal_name")
        }

    def get(self, client_id: str | None) -> dict | None:
        if not client_id:
            return None
        return self._masters.get(client_id)

    def register(
        self,
        client_id: str,
        internal_name: str,
        freee_id: int | None = None,
        mf_name: str | None = None,
        yayoi_name: str | None = None,
    ) -> None:
        """顧問先固有の勘定科目マッピングを登録する。"""
        master = self._masters.setdefault(client_id, {})
        master[internal_name] = {
            "freee_id": freee_id,
            "mf":       mf_name or internal_name,
            "yayoi":    yayoi_name or internal_name,
        }


# シングルトン
_client_master = ClientAccountMaster()


def get_client_master() -> ClientAccountMaster:
    return _client_master
