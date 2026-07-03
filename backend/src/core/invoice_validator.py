"""インボイス登録番号（適格請求書発行事業者番号）ルールベース検証モジュール。

AI に依存せず、確定的なルールとチェックサム検証で正確に抽出する。

仕様（国税庁 告示第 23 号）:
  - 形式: T + 13桁の数字
  - 法人の場合: T + 法人番号（12桁）+ チェックデジット（1桁）
  - 個人の場合: T + 独自の13桁番号（チェックデジットは別アルゴリズム）

法人番号チェックデジット計算:
  d = 9 - (Σ P_n * A_n) mod 9
  P_n = 偶数桁位置は 2、奇数桁位置は 1
  A_n = 右から n 番目の桁の数字（1桁目がチェックデジット）
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class InvoiceValidationResult:
    """インボイス番号検証結果。"""
    raw_text: str              # 原文テキスト
    number: str | None         # 正規化後の番号（T+13桁）
    is_valid: bool             # チェックデジット検証合格
    is_corporate: bool | None  # True=法人、None=判定不能
    error: str | None          # エラーメッセージ


# ── 正規表現パターン ────────────────────────────────────────────────
# OCR 誤認識パターンも吸収:
#   - "T" が認識されない、スペースが入る、T が全角
#   - 数字が全角（０〜９）
_PATTERNS = [
    # 標準: T1234567890123
    re.compile(r"[Tｔ]\s*(\d{13})", re.IGNORECASE),
    # 全角T: Ｔ1234567890123
    re.compile(r"[Ｔ]\s*(\d{13})"),
    # T + 全角数字
    re.compile(r"[TＴ]\s*([０-９]{13})"),
    # 「登録番号」ラベル付き
    re.compile(r"(?:登録番号|インボイス番号|適格請求書)[^\dTＴ]*[TＴ]?\s*(\d{13})"),
    # ハイフン区切りの法人番号 (1-2345-6789-0123)
    re.compile(r"(\d{1}[-ー]\d{4}[-ー]\d{4}[-ー]\d{4})"),
]

# 全角数字→半角変換テーブル
_ZEN_TO_HAN = str.maketrans("０１２３４５６７８９", "0123456789")


class InvoiceNumberValidator:
    """インボイス登録番号の抽出・検証クラス。

    AI の OCR 結果テキストから確定的なルールでインボイス番号を取得する。

    使い方:
        validator = InvoiceNumberValidator()
        results = validator.extract_all(ocr_text)
        best = validator.extract_best(ocr_text)
        print(best.number)  # "T1234567890123"
    """

    def extract_best(self, text: str) -> InvoiceValidationResult:
        """テキストから最も確実なインボイス番号を1件抽出する。

        チェックデジット合格 → 不合格の優先順位で返す。
        """
        results = self.extract_all(text)
        if not results:
            return InvoiceValidationResult(
                raw_text=text[:100],
                number=None,
                is_valid=False,
                is_corporate=None,
                error="インボイス番号が見つかりません",
            )
        # チェックデジット合格を優先
        valid = [r for r in results if r.is_valid]
        return valid[0] if valid else results[0]

    def extract_all(self, text: str) -> list[InvoiceValidationResult]:
        """テキストから全てのインボイス番号候補を抽出する。"""
        if not text:
            return []

        # 前処理: 全角→半角
        text_normalized = text.translate(_ZEN_TO_HAN)

        found: list[InvoiceValidationResult] = []
        seen: set[str] = set()

        for pattern in _PATTERNS:
            for m in pattern.finditer(text_normalized):
                raw_digits = m.group(1).replace("-", "").replace("ー", "")
                raw_digits = raw_digits.translate(_ZEN_TO_HAN)

                # 13桁の数字になるよう調整
                if len(raw_digits) != 13:
                    continue

                t_number = f"T{raw_digits}"

                if t_number in seen:
                    continue
                seen.add(t_number)

                result = self.validate(t_number)
                found.append(result)

        return found

    def validate(self, t_number: str) -> InvoiceValidationResult:
        """T番号の形式とチェックデジットを検証する。

        Args:
            t_number: "T1234567890123" 形式の文字列

        Returns:
            InvoiceValidationResult
        """
        # 形式チェック
        normalized = t_number.strip().upper()
        if not normalized.startswith("T"):
            return InvoiceValidationResult(
                raw_text=t_number,
                number=None,
                is_valid=False,
                is_corporate=None,
                error="T で始まる必要があります",
            )

        digits = normalized[1:]
        if len(digits) != 13:
            return InvoiceValidationResult(
                raw_text=t_number,
                number=None,
                is_valid=False,
                is_corporate=None,
                error=f"T の後ろは13桁が必要です（実際: {len(digits)}桁）",
            )

        if not digits.isdigit():
            return InvoiceValidationResult(
                raw_text=t_number,
                number=None,
                is_valid=False,
                is_corporate=None,
                error="数字以外の文字が含まれています",
            )

        # 法人番号チェックデジット検証
        is_valid, is_corporate = self._verify_check_digit(digits)

        return InvoiceValidationResult(
            raw_text=t_number,
            number=normalized,
            is_valid=is_valid,
            is_corporate=is_corporate,
            error=None if is_valid else "チェックデジット不一致（番号を手動で確認してください）",
        )

    @staticmethod
    def _verify_check_digit(digits_13: str) -> tuple[bool, bool | None]:
        """法人番号チェックデジットを検証する。

        アルゴリズム（国税庁 法人番号公表サイト仕様）:
          - 右から n 番目の桁 A_n（1始まり）
          - P_n = n が偶数なら 2、奇数なら 1
          - sum = Σ(A_n * P_n) for n = 2〜13
          - check = 9 - (sum mod 9)
          - digits_13[0] == check (先頭1桁がチェックデジット)

        法人番号以外（個人事業主の T 番号等）は国税庁 DB 照合が必要なため
        チェックデジット不一致でも「不確実」として扱う。
        """
        d = [int(c) for c in digits_13]  # d[0] = チェックデジット, d[1]〜d[12] = 本体

        total = 0
        for n in range(2, 14):  # n = 2〜13
            a_n = d[13 - n]     # 右から n 番目 = インデックス 13-n
            p_n = 2 if n % 2 == 0 else 1
            total += a_n * p_n

        expected_check = 9 - (total % 9)
        actual_check = d[0]

        is_corporate = (actual_check == expected_check)
        # 一致しない場合は個人事業主の可能性もあるが判定不能
        return is_corporate, is_corporate if is_corporate else None


# ── ユーティリティ関数 ─────────────────────────────────────────────────

def extract_invoice_number(text: str) -> str | None:
    """OCR テキストから最も確実なインボイス番号を返す（簡易版）。

    Returns:
        "T1234567890123" または None
    """
    v = InvoiceNumberValidator()
    result = v.extract_best(text)
    return result.number if result.number else None


def is_valid_invoice_number(t_number: str) -> bool:
    """T番号の形式とチェックデジットを検証する（簡易版）。"""
    v = InvoiceNumberValidator()
    return v.validate(t_number).is_valid
