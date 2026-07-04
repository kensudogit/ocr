"""PII（個人情報・機密情報）マスクモジュール。

クラウド AI（OpenAI / Gemini）に送信する前に
最機微情報を置換文字列で隠す。

マスク対象:
  - 銀行口座番号（金融機関コード・支店番号・口座番号）
  - マイナンバー（個人番号 12桁）
  - クレジットカード番号（16桁）
  - 法人番号（13桁）→ 置換せず保持（インボイス番号として必要）
  - 電話番号（オプション: 設定に応じて）
  - メールアドレス（オプション）

マスク後に AI で処理し、結果に元の値を戻すことで
「クラウド AI に機微情報を渡さない」を実現する。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MaskResult:
    """マスク処理の結果。"""
    masked_text: str                  # マスク済みテキスト（AIに渡す）
    restored_values: dict[str, str]   # {placeholder: original_value}
    mask_count: int                   # マスクした項目数


class PiiMasker:
    """PII マスク/復元クラス。

    使い方:
        masker = PiiMasker()
        result = masker.mask(ocr_text)
        ai_result = await vlm.extract(result.masked_text)  # AIはマスク済みテキストを受け取る
        restored = masker.restore(ai_result_text, result.restored_values)
    """

    def __init__(
        self,
        mask_bank_accounts: bool = True,
        mask_my_number: bool = True,
        mask_card_numbers: bool = True,
        mask_phone_numbers: bool = False,   # 電話は取引先特定に必要なため OFF がデフォルト
        mask_email: bool = False,
    ) -> None:
        self.mask_bank_accounts = mask_bank_accounts
        self.mask_my_number     = mask_my_number
        self.mask_card_numbers  = mask_card_numbers
        self.mask_phone_numbers = mask_phone_numbers
        self.mask_email         = mask_email

        self._counter = 0

    def mask(self, text: str) -> MaskResult:
        """テキスト内の PII をプレースホルダに置換する。

        Args:
            text: OCR 生テキスト

        Returns:
            MaskResult: マスク済みテキストと復元辞書
        """
        self._counter = 0
        masked = text
        restored: dict[str, str] = {}

        if self.mask_my_number:
            masked, new_restored = self._mask_my_number(masked)
            restored.update(new_restored)

        if self.mask_bank_accounts:
            masked, new_restored = self._mask_bank_accounts(masked)
            restored.update(new_restored)

        if self.mask_card_numbers:
            masked, new_restored = self._mask_card_numbers(masked)
            restored.update(new_restored)

        if self.mask_phone_numbers:
            masked, new_restored = self._mask_phone_numbers(masked)
            restored.update(new_restored)

        if self.mask_email:
            masked, new_restored = self._mask_email(masked)
            restored.update(new_restored)

        return MaskResult(
            masked_text=masked,
            restored_values=restored,
            mask_count=len(restored),
        )

    def restore(self, text: str, restored_values: dict[str, str]) -> str:
        """プレースホルダを元の値に戻す（AI レスポンスの後処理）。"""
        result = text
        for placeholder, original in restored_values.items():
            result = result.replace(placeholder, original)
        return result

    # ──────────────────────────────────────────────────────────────
    # マスク処理（各情報種別）
    # ──────────────────────────────────────────────────────────────

    def _mask_my_number(self, text: str) -> tuple[str, dict[str, str]]:
        """マイナンバー（個人番号: 12桁）をマスクする。

        マイナンバーは 12 桁で、以下のコンテキストで出現:
          - 「個人番号」「マイナンバー」の後ろ
          - ハイフン区切り: 1234-5678-9012
          - スペース区切り: 1234 5678 9012
        """
        restored = {}
        patterns = [
            # 「個人番号」ラベル付き
            re.compile(r"(?:個人番号|マイナンバー|My\s*Number)[^\d]*(\d{4}[\s\-]?\d{4}[\s\-]?\d{4})"),
            # ハイフン区切り12桁
            re.compile(r"(?<!\d)(\d{4}[-\s]\d{4}[-\s]\d{4})(?!\d)"),
        ]
        for pat in patterns:
            def replace_fn(m: re.Match) -> str:
                original = m.group(1)
                placeholder = f"[MY_NUMBER_{self._counter}]"
                restored[placeholder] = original
                self._counter += 1
                return m.group(0).replace(original, placeholder)
            text = pat.sub(replace_fn, text)
        return text, restored

    def _mask_bank_accounts(self, text: str) -> tuple[str, dict[str, str]]:
        """銀行口座情報をマスクする。

        パターン:
          - 金融機関コード（4桁）+ 支店コード（3桁）+ 口座番号（7桁）
          - 「口座番号」「普通」「当座」ラベルの後
        """
        restored = {}
        patterns = [
            # 「口座番号」ラベルの後の数字列
            re.compile(r"(?:口座番号|普通預金|当座預金|預金口座)[^\d]*(\d{7,8})"),
            # 「振込先」の口座番号
            re.compile(r"(?:振込先|振込口座)[^\d]*(\d{4}[-\s]\d{3}[-\s]\d{7,8})"),
            # 金融機関コード＋支店＋口座の組み合わせ
            re.compile(r"(?<!\d)(\d{4}[-\s]\d{3}[-\s]\d{7,8})(?!\d)"),
        ]
        for pat in patterns:
            def replace_fn(m: re.Match) -> str:
                original = m.group(1)
                placeholder = f"[BANK_ACCOUNT_{self._counter}]"
                restored[placeholder] = original
                self._counter += 1
                return m.group(0).replace(original, placeholder)
            text = pat.sub(replace_fn, text)
        return text, restored

    def _mask_card_numbers(self, text: str) -> tuple[str, dict[str, str]]:
        """クレジットカード番号をマスクする（16桁の数字列）。

        Luhn アルゴリズムで検証し、カード番号らしい数字のみマスク。
        インボイス番号（T+13桁）はマスク対象外。
        """
        restored = {}
        # カード番号パターン: 4-4-4-4 or 4444444444444444
        pattern = re.compile(
            r"(?<!\d)(?<![Tt])(\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}|\d{16})(?!\d)"
        )
        def replace_fn(m: re.Match) -> str:
            original = m.group(1)
            digits = re.sub(r"[\s\-]", "", original)
            if self._luhn_check(digits):
                placeholder = f"[CARD_NUMBER_{self._counter}]"
                restored[placeholder] = original
                self._counter += 1
                return placeholder
            return m.group(0)
        text = pattern.sub(replace_fn, text)
        return text, restored

    def _mask_phone_numbers(self, text: str) -> tuple[str, dict[str, str]]:
        """電話番号をマスクする。"""
        restored = {}
        pattern = re.compile(r"(?:TEL|Tel|電話)?[\s:：]*(\d{2,4}[-\-]\d{2,4}[-\-]\d{3,4})")
        def replace_fn(m: re.Match) -> str:
            original = m.group(1)
            placeholder = f"[PHONE_{self._counter}]"
            restored[placeholder] = original
            self._counter += 1
            return m.group(0).replace(original, placeholder)
        text = pattern.sub(replace_fn, text)
        return text, restored

    def _mask_email(self, text: str) -> tuple[str, dict[str, str]]:
        """メールアドレスをマスクする。"""
        restored = {}
        pattern = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
        def replace_fn(m: re.Match) -> str:
            original = m.group(0)
            placeholder = f"[EMAIL_{self._counter}]"
            restored[placeholder] = original
            self._counter += 1
            return placeholder
        text = pattern.sub(replace_fn, text)
        return text, restored

    @staticmethod
    def _luhn_check(digits: str) -> bool:
        """Luhn アルゴリズムでクレジットカード番号を検証する。"""
        if not digits.isdigit() or len(digits) < 13:
            return False
        # 全桁が同一の番号は無効（例: 0000000000000000）
        if len(set(digits)) == 1:
            return False
        total = 0
        for i, d in enumerate(reversed(digits)):
            n = int(d)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        return total % 10 == 0


# ── 画像ベースのマスク（PIIを含む画像領域をブロック） ─────────────────────

class ImageRegionMasker:
    """画像内の特定領域（口座番号等）をモザイクでマスクする。

    使用シーン:
      - カード明細の口座番号が印刷されている場合
      - VLM に送る画像から機密情報を事前に除去
    """

    def mask_regions(
        self,
        image_array,   # np.ndarray
        regions: list[tuple[int, int, int, int]],  # (x, y, w, h) のリスト
        method: str = "black",  # "black" | "blur" | "mosaic"
    ):
        """指定領域をマスクする。

        Args:
            image_array: NumPy BGR 配列
            regions:     マスクする矩形リスト [(x, y, w, h)]
            method:      "black"=黒塗り, "blur"=ぼかし, "mosaic"=モザイク

        Returns:
            np.ndarray: マスク済み画像
        """
        import numpy as np
        import cv2

        result = image_array.copy()
        for (x, y, w, h) in regions:
            x, y = max(0, x), max(0, y)
            x2 = min(image_array.shape[1], x + w)
            y2 = min(image_array.shape[0], y + h)

            if method == "black":
                result[y:y2, x:x2] = 0
            elif method == "blur":
                result[y:y2, x:x2] = cv2.GaussianBlur(result[y:y2, x:x2], (51, 51), 0)
            elif method == "mosaic":
                # モザイク: 縮小して拡大
                roi = result[y:y2, x:x2]
                small = cv2.resize(roi, (max(1, (x2-x)//10), max(1, (y2-y)//10)))
                result[y:y2, x:x2] = cv2.resize(small, (x2-x, y2-y), interpolation=cv2.INTER_NEAREST)

        return result
