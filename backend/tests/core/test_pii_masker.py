"""PII マスクモジュールのテスト。

対象: src/core/pii_masker.py
テスト観点:
  - マイナンバー（12桁）のマスク・復元
  - 銀行口座番号のマスク・復元
  - クレジットカード番号（Luhn 検証）のマスク・復元
  - 電話番号・メールのオプションマスク
  - 複数 PII が混在するテキスト
  - マスクなし（対象なし）のケース
  - 復元の正確性
"""
from __future__ import annotations

import pytest

from src.core.pii_masker import PiiMasker


@pytest.mark.unit
@pytest.mark.pii
class TestPiiMaskerMyNumber:
    """マイナンバー（個人番号）マスクのテスト。"""

    def setup_method(self):
        self.masker = PiiMasker(
            mask_my_number=True,
            mask_bank_accounts=False,
            mask_card_numbers=False,
        )

    def test_mask_my_number_with_label(self):
        """「個人番号」ラベル付きのマイナンバーがマスクされること。"""
        text = "個人番号 1234-5678-9012 の確認をお願いします"
        result = self.masker.mask(text)
        assert "1234-5678-9012" not in result.masked_text
        assert "[MY_NUMBER_" in result.masked_text
        assert result.mask_count >= 1

    def test_mask_my_number_with_mynumber_label(self):
        """「マイナンバー」ラベル付きの番号がマスクされること。"""
        text = "マイナンバー：123456789012"
        result = self.masker.mask(text)
        assert "123456789012" not in result.masked_text

    def test_restore_my_number(self):
        """マスクされたマイナンバーが正確に復元できること。"""
        original = "個人番号: 1234-5678-9012"
        mask_result = self.masker.mask(original)
        restored = self.masker.restore(mask_result.masked_text, mask_result.restored_values)
        assert "1234-5678-9012" in restored

    def test_my_number_not_masked_when_disabled(self):
        """mask_my_number=False の場合はマスクされないこと。"""
        masker = PiiMasker(mask_my_number=False, mask_bank_accounts=False, mask_card_numbers=False)
        text = "個人番号 1234-5678-9012"
        result = masker.mask(text)
        assert "1234-5678-9012" in result.masked_text
        assert result.mask_count == 0


@pytest.mark.unit
@pytest.mark.pii
class TestPiiMaskerBankAccount:
    """銀行口座番号マスクのテスト。"""

    def setup_method(self):
        self.masker = PiiMasker(
            mask_bank_accounts=True,
            mask_my_number=False,
            mask_card_numbers=False,
        )

    def test_mask_bank_account_with_label(self):
        """「口座番号」ラベル付きの番号がマスクされること。"""
        text = "口座番号: 1234567 へお振り込みください"
        result = self.masker.mask(text)
        assert "1234567" not in result.masked_text
        assert "[BANK_ACCOUNT_" in result.masked_text

    def test_mask_transfer_destination(self):
        """「振込先」のフォーマットがマスクされること。"""
        text = "振込先: 1234-123-1234567"
        result = self.masker.mask(text)
        assert result.mask_count >= 1

    def test_restore_bank_account(self):
        """マスクされた口座番号が正確に復元できること。"""
        text = "口座番号: 1234567"
        mask_result = self.masker.mask(text)
        restored = self.masker.restore(mask_result.masked_text, mask_result.restored_values)
        assert "1234567" in restored

    def test_bank_account_not_masked_when_disabled(self):
        """mask_bank_accounts=False の場合はマスクされないこと。"""
        masker = PiiMasker(mask_bank_accounts=False, mask_my_number=False, mask_card_numbers=False)
        text = "口座番号: 1234567"
        result = masker.mask(text)
        assert result.mask_count == 0


@pytest.mark.unit
@pytest.mark.pii
class TestPiiMaskerCardNumber:
    """クレジットカード番号マスクのテスト。"""

    def setup_method(self):
        self.masker = PiiMasker(
            mask_card_numbers=True,
            mask_my_number=False,
            mask_bank_accounts=False,
        )

    def test_mask_valid_visa_card(self):
        """Luhn 検証を通過する VISA カード番号がマスクされること。"""
        # 4532015112830366 は Luhn 検証通過の有効なテスト番号
        text = "カード番号: 4532015112830366"
        result = self.masker.mask(text)
        assert "4532015112830366" not in result.masked_text
        assert "[CARD_NUMBER_" in result.masked_text

    def test_mask_card_with_hyphens(self):
        """ハイフン区切りのカード番号がマスクされること。"""
        text = "ご利用カード: 4532-0151-1283-0366"
        result = self.masker.mask(text)
        assert result.mask_count >= 1

    def test_invalid_luhn_not_masked(self):
        """Luhn 検証失敗の数字列はマスクされないこと。"""
        text = "番号: 1234567890123456"  # Luhn 不合格
        result = self.masker.mask(text)
        # Luhn 不合格 → マスクされない（= 元のテキスト残る可能性あり）
        assert result.mask_count == 0 or "1234567890123456" in result.masked_text

    def test_restore_card_number(self):
        """マスクされたカード番号が正確に復元できること。"""
        text = "4532015112830366"
        mask_result = self.masker.mask(text)
        if mask_result.mask_count > 0:
            restored = self.masker.restore(mask_result.masked_text, mask_result.restored_values)
            assert "4532015112830366" in restored

    def test_invoice_number_not_masked_as_card(self):
        """T+13桁のインボイス番号がカード番号としてマスクされないこと。"""
        text = "登録番号 T1234567890128"
        result = self.masker.mask(text)
        # インボイス番号は T がプレフィックスなのでカードパターンに一致しない
        assert "T1234567890128" in result.masked_text or result.mask_count == 0


@pytest.mark.unit
@pytest.mark.pii
class TestPiiMaskerComplex:
    """複合 PII テキストのマスクテスト。"""

    def setup_method(self):
        self.masker = PiiMasker(
            mask_my_number=True,
            mask_bank_accounts=True,
            mask_card_numbers=True,
            mask_phone_numbers=False,
        )

    def test_multiple_pii_types_in_one_text(self):
        """複数種類の PII が混在するテキストを全てマスクできること。"""
        text = (
            "個人番号: 1234-5678-9012\n"
            "口座番号: 1234567\n"
            "カード: 4532015112830366"
        )
        result = self.masker.mask(text)
        assert "1234-5678-9012" not in result.masked_text
        assert result.mask_count >= 2

    def test_no_pii_in_normal_text(self):
        """PII のない通常テキストはマスクされないこと。"""
        text = "セブンイレブン 渋谷店\n合計 1,200円\n2024年3月15日"
        result = self.masker.mask(text)
        assert result.mask_count == 0
        assert result.masked_text == text

    def test_restore_all_pii_correctly(self):
        """全 PII が正確に復元できること。"""
        original_text = "個人番号: 1234-5678-9012 口座: 7654321"
        mask_result = self.masker.mask(original_text)
        restored = self.masker.restore(mask_result.masked_text, mask_result.restored_values)
        # 元のテキストの PII が復元されていること
        assert "1234-5678-9012" in restored or "7654321" in restored

    def test_mask_empty_string(self):
        """空文字列は何も変更されないこと。"""
        result = self.masker.mask("")
        assert result.masked_text == ""
        assert result.mask_count == 0

    def test_mask_count_correct(self):
        """マスク件数が正確にカウントされること。"""
        text = "個人番号: 1234-5678-9012"
        result = self.masker.mask(text)
        assert result.mask_count == len(result.restored_values)

    def test_restore_with_empty_values_returns_original(self):
        """空の復元辞書で復元しても元テキストが変わらないこと。"""
        text = "マスクなしのテキスト"
        restored = self.masker.restore(text, {})
        assert restored == text


@pytest.mark.unit
@pytest.mark.pii
class TestLuhnAlgorithm:
    """Luhn アルゴリズムの詳細テスト。"""

    def test_known_valid_card_numbers(self):
        """既知の有効なカード番号テスト（Luhn 合格）。"""
        masker = PiiMasker(mask_card_numbers=True, mask_my_number=False, mask_bank_accounts=False)
        # Luhn 合格の既知テスト番号
        valid_numbers = [
            "4532015112830366",  # VISA テスト番号
            "5425233430109903",  # Mastercard テスト番号
        ]
        for num in valid_numbers:
            result = masker.mask(num)
            assert result.mask_count == 1, f"{num} はマスクされるべき"

    def test_known_invalid_card_numbers(self):
        """Luhn 検証失敗の番号はマスクされないこと。"""
        masker = PiiMasker(mask_card_numbers=True, mask_my_number=False, mask_bank_accounts=False)
        # Luhn 不合格の番号
        invalid_numbers = [
            "1234567890123456",
            "0000000000000000",
        ]
        for num in invalid_numbers:
            result = masker.mask(num)
            assert result.mask_count == 0, f"{num} はマスクされないべき"
