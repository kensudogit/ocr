"""共通仕訳データモデル・アダプタのテスト。

対象: src/core/journal_model.py
テスト観点:
  - JournalEntry の基本構造
  - FreeeAccountAdapter が正しい account_item_id を返すこと
  - MoneyForwardAccountAdapter が完全一致テキストを返すこと
  - YayoiAccountAdapter が弥生形式のテキストを返すこと
  - ClientAccountMaster による顧問先固有マッピング
  - 不明な勘定科目のフォールバック
  - get_adapter ファクトリ関数
"""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime

import pytest

from src.core.journal_model import (
    ClientAccountMaster,
    FreeeAccountAdapter,
    JournalEntry,
    JournalLineItem,
    MoneyForwardAccountAdapter,
    YayoiAccountAdapter,
    get_adapter,
    get_client_master,
)


def make_entry(
    debit_account: str = "消耗品費",
    credit_account: str = "現金",
    total_amount: float = 1200.0,
    tax_category: str = "課税仕入10%",
) -> JournalEntry:
    return JournalEntry(
        document_id="test-doc-001",
        client_id="client-001",
        transaction_date=datetime(2024, 3, 15),
        vendor_name="テスト商店",
        total_amount=Decimal(str(total_amount)),
        debit_account=debit_account,
        credit_account=credit_account,
        tax_category=tax_category,
    )


@pytest.mark.unit
class TestFreeeAccountAdapter:
    """FreeeAccountAdapter のテスト。"""

    def setup_method(self):
        self.adapter = FreeeAccountAdapter()

    def test_shomohinhi_returns_correct_id(self):
        """消耗品費 → freee account_item_id 1012 を返すこと。"""
        entry = make_entry(debit_account="消耗品費")
        result = self.adapter.get_debit_account(entry)
        assert result == 1012

    def test_ryohi_kotssuhi_returns_correct_id(self):
        """旅費交通費 → freee account_item_id 1013 を返すこと。"""
        entry = make_entry(debit_account="旅費交通費")
        result = self.adapter.get_debit_account(entry)
        assert result == 1013

    def test_cash_returns_correct_id(self):
        """現金 → freee account_item_id 1 を返すこと。"""
        entry = make_entry(credit_account="現金")
        result = self.adapter.get_credit_account(entry)
        assert result == 1

    def test_unknown_account_returns_fallback_id(self):
        """未登録の勘定科目はフォールバック ID（消耗品費 1012）を返すこと。"""
        entry = make_entry(debit_account="存在しない科目")
        result = self.adapter.get_debit_account(entry)
        assert isinstance(result, int)
        assert result > 0

    def test_tax_code_10pct(self):
        """課税仕入10% → freee tax_code 17 を返すこと。"""
        result = self.adapter.get_tax_code("課税仕入10%")
        assert result == 17

    def test_tax_code_non_taxable(self):
        """非課税 → freee tax_code 14 を返すこと。"""
        result = self.adapter.get_tax_code("非課税")
        assert result == 14

    def test_all_standard_accounts_return_int(self):
        """標準勘定科目は全て整数 ID を返すこと。"""
        standard_accounts = [
            "消耗品費", "旅費交通費", "交際費", "会議費", "通信費",
            "水道光熱費", "広告宣伝費", "新聞図書費", "福利厚生費",
            "外注費", "地代家賃", "修繕費", "雑費", "現金", "未払金", "普通預金",
        ]
        for account in standard_accounts:
            entry = make_entry(debit_account=account)
            result = self.adapter.get_debit_account(entry)
            assert isinstance(result, int), f"{account} が整数でない: {result}"


@pytest.mark.unit
class TestMoneyForwardAccountAdapter:
    """MoneyForwardAccountAdapter のテスト。"""

    def setup_method(self):
        self.adapter = MoneyForwardAccountAdapter()

    def test_shomohinhi_returns_text(self):
        """消耗品費 → MF 形式のテキストを返すこと。"""
        entry = make_entry(debit_account="消耗品費")
        result = self.adapter.get_debit_account(entry)
        assert isinstance(result, str)
        assert result == "消耗品費"

    def test_all_accounts_return_str(self):
        """全標準勘定科目が文字列を返すこと。"""
        standard = ["消耗品費", "旅費交通費", "現金"]
        for acc in standard:
            entry = make_entry(debit_account=acc)
            assert isinstance(self.adapter.get_debit_account(entry), str)

    def test_tax_code_10pct_is_string(self):
        """MF の税区分コードが文字列であること。"""
        result = self.adapter.get_tax_code("課税仕入10%")
        assert isinstance(result, str)

    def test_unknown_account_returns_string(self):
        """未登録科目でも文字列（内部名称）を返すこと。"""
        entry = make_entry(debit_account="謎の科目")
        result = self.adapter.get_debit_account(entry)
        assert isinstance(result, str)
        assert result == "謎の科目"


@pytest.mark.unit
class TestYayoiAccountAdapter:
    """YayoiAccountAdapter のテスト。"""

    def setup_method(self):
        self.adapter = YayoiAccountAdapter()

    def test_shomohinhi_returns_yayoi_text(self):
        """消耗品費 → 弥生形式のテキストを返すこと。"""
        entry = make_entry(debit_account="消耗品費")
        result = self.adapter.get_debit_account(entry)
        assert isinstance(result, str)
        assert "消耗品費" in result

    def test_tax_code_10pct_is_yayoi_code(self):
        """課税仕入10% → 弥生の税コード "10" を返すこと。"""
        result = self.adapter.get_tax_code("課税仕入10%")
        assert result == "10"

    def test_tax_code_8pct_reduced(self):
        """課税仕入8%軽減 → 弥生の税コード "11" を返すこと。"""
        result = self.adapter.get_tax_code("課税仕入8%軽減")
        assert result == "11"

    def test_non_taxable_yayoi_code(self):
        """非課税 → 弥生の税コード "14" を返すこと。"""
        result = self.adapter.get_tax_code("非課税")
        assert result == "14"


@pytest.mark.unit
class TestClientAccountMaster:
    """ClientAccountMaster のテスト。"""

    def setup_method(self):
        self.master = ClientAccountMaster()

    def test_register_and_get_mapping(self):
        """登録したマッピングを取得できること。"""
        client_id = "test-client-master"
        self.master.register(
            client_id=client_id,
            internal_name="交通費",
            freee_id=1013,
            mf_name="旅費交通費",
            yayoi_name="旅費交通費",
        )
        client_map = self.master.get(client_id)
        assert client_map is not None
        assert "交通費" in client_map

    def test_load_from_db_mappings(self):
        """DB マッピングのバルクロードができること。"""
        client_id = "test-client-bulk"
        mappings = [
            {"internal_name": "旅費", "freee_id": 1013, "mf_name": "旅費交通費", "yayoi_name": "旅費交通費"},
            {"internal_name": "消耗品", "freee_id": 1012, "mf_name": "消耗品費", "yayoi_name": "消耗品費"},
        ]
        self.master.load(client_id, mappings)
        client_map = self.master.get(client_id)
        assert client_map is not None
        assert "旅費" in client_map
        assert "消耗品" in client_map

    def test_get_nonexistent_client_returns_none(self):
        """未登録の顧問先は None を返すこと。"""
        result = self.master.get("nonexistent-client-999")
        assert result is None

    def test_get_none_client_id_returns_none(self):
        """None の顧問先 ID は None を返すこと。"""
        result = self.master.get(None)
        assert result is None

    def test_custom_mapping_overrides_default_in_adapter(self):
        """顧問先固有マッピングがデフォルトより優先されること。"""
        client_id = "test-override-client"
        # 内部名称 "交通費" を freee ID 9999 にマッピング
        self.master.register(
            client_id=client_id,
            internal_name="交通費",
            freee_id=9999,
            mf_name="交通費カスタム",
            yayoi_name="交通費カスタム",
        )
        client_map = self.master.get(client_id)
        adapter = FreeeAccountAdapter()
        entry = make_entry(debit_account="交通費")
        result = adapter.get_debit_account(entry, client_master=client_map)
        assert result == 9999


@pytest.mark.unit
class TestGetAdapter:
    """get_adapter ファクトリ関数のテスト。"""

    def test_get_freee_adapter(self):
        """'freee' → FreeeAccountAdapter を返すこと。"""
        adapter = get_adapter("freee")
        assert isinstance(adapter, FreeeAccountAdapter)

    def test_get_money_forward_adapter(self):
        """'money_forward' → MoneyForwardAccountAdapter を返すこと。"""
        adapter = get_adapter("money_forward")
        assert isinstance(adapter, MoneyForwardAccountAdapter)

    def test_get_yayoi_adapter(self):
        """'yayoi' → YayoiAccountAdapter を返すこと。"""
        adapter = get_adapter("yayoi")
        assert isinstance(adapter, YayoiAccountAdapter)

    def test_unknown_software_returns_default(self):
        """未知のソフト名はデフォルト（MF）アダプタを返すこと。"""
        adapter = get_adapter("unknown_software")
        assert isinstance(adapter, MoneyForwardAccountAdapter)
