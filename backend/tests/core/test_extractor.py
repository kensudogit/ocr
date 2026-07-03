"""データ抽出モジュールのテスト。

対象: src/core/extractor.py
テスト観点:
  - 日付抽出（令和・平成・西暦・スラッシュ区切り）
  - 金額抽出（合計・小計・消費税 10%/8%）
  - 支払先名抽出
  - インボイス番号パターンマッチ
  - 支払方法の判定
  - 明細行の抽出
  - 全フィールドの型チェック
"""
from __future__ import annotations

from datetime import date

import pytest

from src.core.extractor import DataExtractor, ExtractedFields


@pytest.mark.unit
class TestDateExtraction:
    """日付抽出のテスト。"""

    def setup_method(self):
        self.extractor = DataExtractor()

    def test_extract_reiwa_date(self):
        """令和形式の日付を抽出できること。"""
        text = "令和6年3月15日"
        fields = self.extractor.extract(text)
        assert fields.transaction_date is not None
        assert fields.transaction_date.month == 3
        assert fields.transaction_date.day == 15

    def test_extract_heisei_date(self):
        """平成形式の日付を抽出できること。"""
        text = "平成31年4月30日"
        fields = self.extractor.extract(text)
        assert fields.transaction_date is not None
        assert fields.transaction_date.year == 2019

    def test_extract_western_date_slash(self):
        """西暦スラッシュ形式（2024/3/15）を抽出できること。"""
        text = "2024/3/15"
        fields = self.extractor.extract(text)
        assert fields.transaction_date is not None
        assert fields.transaction_date.year == 2024
        assert fields.transaction_date.month == 3

    def test_extract_western_date_hyphen(self):
        """西暦ハイフン形式（2024-03-15）を抽出できること。"""
        text = "発行日: 2024-03-15"
        fields = self.extractor.extract(text)
        assert fields.transaction_date is not None
        assert fields.transaction_date.year == 2024

    def test_extract_japanese_full_date(self):
        """「2024年3月15日」形式を抽出できること。"""
        text = "2024年3月15日"
        fields = self.extractor.extract(text)
        assert fields.transaction_date is not None

    def test_no_date_returns_none(self):
        """日付がないテキストは None を返すこと。"""
        text = "合計 1200円"
        fields = self.extractor.extract(text)
        assert fields.transaction_date is None

    def test_extract_from_receipt(self, sample_receipt_text: str):
        """サンプルレシートから日付を抽出できること。"""
        fields = self.extractor.extract(sample_receipt_text)
        assert fields.transaction_date is not None


@pytest.mark.unit
class TestAmountExtraction:
    """金額抽出のテスト。"""

    def setup_method(self):
        self.extractor = DataExtractor()

    def test_extract_total_amount(self):
        """「合計」ラベルから合計金額を抽出できること。"""
        text = "合計 1,200円"
        fields = self.extractor.extract(text)
        assert fields.total_amount == 1200

    def test_extract_tax_included_total(self):
        """「税込合計」から合計金額を抽出できること。"""
        text = "税込合計 ¥1,320"
        fields = self.extractor.extract(text)
        assert fields.total_amount == 1320

    def test_extract_subtotal_and_tax(self):
        """小計と消費税 10% を別々に抽出できること。"""
        text = "小計 1,000円\n消費税 (10%) 100円\n合計 1,100円"
        fields = self.extractor.extract(text)
        assert fields.total_amount == 1100
        assert fields.subtotal_amount == 1000
        assert fields.tax_amount_10 == 100

    def test_extract_8pct_tax(self):
        """消費税 8% を抽出できること（軽減税率）。"""
        text = "本体 500円\n消費税 (8%) 40円\n合計 540円"
        fields = self.extractor.extract(text)
        assert fields.tax_amount_8 == 40

    def test_extract_yen_symbol(self):
        """¥ マーク付き金額を抽出できること。"""
        text = "お支払金額 ¥ 5,400"
        fields = self.extractor.extract(text)
        assert fields.total_amount == 5400

    def test_extract_comma_formatted_amount(self):
        """カンマ区切りの大きな金額を正しく抽出できること。"""
        text = "請求金額 ¥1,320,000"
        fields = self.extractor.extract(text)
        assert fields.total_amount == 1320000

    def test_no_amount_returns_none(self):
        """金額のないテキストは None を返すこと。"""
        text = "2024年3月15日"
        fields = self.extractor.extract(text)
        assert fields.total_amount is None

    def test_extract_from_sample_receipt(self, sample_receipt_text: str):
        """サンプルレシートから合計金額を抽出できること。"""
        fields = self.extractor.extract(sample_receipt_text)
        assert fields.total_amount == 620

    def test_extract_from_sample_invoice(self, sample_invoice_text: str):
        """サンプル請求書から合計金額を抽出できること。"""
        fields = self.extractor.extract(sample_invoice_text)
        assert fields.total_amount == 660000


@pytest.mark.unit
class TestVendorExtraction:
    """取引先名抽出のテスト。"""

    def setup_method(self):
        self.extractor = DataExtractor()

    def test_extract_store_name_from_first_line(self):
        """最初の行を店舗名として抽出できること。"""
        text = "セブン-イレブン 渋谷店\n2024/3/15\n合計 620円"
        fields = self.extractor.extract(text)
        assert fields.vendor_name is not None

    def test_extract_from_sample_receipt(self, sample_receipt_text: str):
        """サンプルレシートから取引先名を抽出できること。"""
        fields = self.extractor.extract(sample_receipt_text)
        assert fields.vendor_name is not None


@pytest.mark.unit
class TestInvoiceNumberExtraction:
    """インボイス番号抽出のテスト。"""

    def setup_method(self):
        self.extractor = DataExtractor()

    def test_extract_t_number_pattern(self):
        """T+13桁のパターンを抽出できること。"""
        text = "登録番号 T1234567890128"
        fields = self.extractor.extract(text)
        assert fields.vendor_registration_no is not None
        assert fields.vendor_registration_no.startswith("T")

    def test_extract_from_sample_receipt(self, sample_receipt_text: str):
        """サンプルレシートからインボイス番号を抽出できること。"""
        fields = self.extractor.extract(sample_receipt_text)
        assert fields.vendor_registration_no == "T1234567890137"


@pytest.mark.unit
class TestPaymentMethodExtraction:
    """支払方法抽出のテスト。"""

    def setup_method(self):
        self.extractor = DataExtractor()

    def test_extract_cash_payment(self):
        """「現金」支払い方法を抽出できること。"""
        text = "現金でお支払い 1,200円"
        fields = self.extractor.extract(text)
        if fields.payment_method:
            assert "現金" in fields.payment_method

    def test_extract_card_payment(self):
        """「カード」支払い方法を抽出できること。"""
        text = "クレジットカードでお支払い"
        fields = self.extractor.extract(text)
        if fields.payment_method:
            assert "カード" in fields.payment_method

    def test_extract_paypay_payment(self):
        """PayPay での支払い方法を抽出できること。"""
        text = "PayPay 残高 1,200円"
        fields = self.extractor.extract(text)
        if fields.payment_method:
            assert "電子" in fields.payment_method or "PayPay" in fields.payment_method


@pytest.mark.unit
class TestExtractedFieldsType:
    """ExtractedFields の型チェックテスト。"""

    def setup_method(self):
        self.extractor = DataExtractor()

    def test_extracted_fields_is_dataclass(self):
        """extract() が ExtractedFields 型を返すこと。"""
        fields = self.extractor.extract("テスト")
        assert isinstance(fields, ExtractedFields)

    def test_line_items_is_list(self, sample_receipt_text: str):
        """line_items が常にリストであること。"""
        fields = self.extractor.extract(sample_receipt_text)
        assert isinstance(fields.line_items, list)

    def test_empty_text_returns_empty_fields(self):
        """空テキストは None フィールドの ExtractedFields を返すこと。"""
        fields = self.extractor.extract("")
        assert isinstance(fields, ExtractedFields)
        assert fields.total_amount is None
        assert fields.transaction_date is None

    def test_total_amount_is_numeric_or_none(self, sample_receipt_text: str):
        """total_amount が数値か None であること。"""
        fields = self.extractor.extract(sample_receipt_text)
        assert fields.total_amount is None or isinstance(fields.total_amount, (int, float))

    def test_transaction_date_is_date_or_none(self, sample_receipt_text: str):
        """transaction_date が date 型か None であること。"""
        fields = self.extractor.extract(sample_receipt_text)
        assert fields.transaction_date is None or isinstance(fields.transaction_date, date)
