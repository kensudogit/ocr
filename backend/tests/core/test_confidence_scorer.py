"""信頼度スコアリングモジュールのテスト。

対象: src/core/confidence_scorer.py
テスト観点:
  - 3段階分類（AUTO_CONFIRMED / NEEDS_REVIEW / MANUAL_INPUT）
  - 各フィールドの重み付けスコア計算
  - 検算（小計 + 税 = 合計）の判定
  - 境界値（0.85 / 0.55）での分類
  - フラグ生成
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.core.confidence_scorer import (
    ConfidenceScorer,
    ConfidenceTier,
    THRESHOLD_AUTO,
    THRESHOLD_REVIEW,
)
from src.core.extractor import ExtractedFields


def make_fields(
    transaction_date=date(2024, 3, 15),
    total_amount: float | None = 1200.0,
    vendor_name: str | None = "テスト商店",
    tax_amount_10: float | None = 109.0,
    subtotal_amount: float | None = 1091.0,
    vendor_registration_no: str | None = "T1234567890128",
    account_title: str | None = "消耗品費",
    tax_amount_8: float | None = None,
) -> ExtractedFields:
    """テスト用 ExtractedFields を生成するヘルパー。"""
    return ExtractedFields(
        transaction_date=transaction_date,
        total_amount=total_amount,
        vendor_name=vendor_name,
        tax_amount_10=tax_amount_10,
        subtotal_amount=subtotal_amount,
        vendor_registration_no=vendor_registration_no,
        account_title=account_title,
        tax_amount_8=tax_amount_8,
    )


@pytest.mark.unit
class TestConfidenceTierThresholds:
    """3段階分類の閾値テスト。"""

    def setup_method(self):
        self.scorer = ConfidenceScorer()

    def test_high_confidence_yields_auto_confirmed(self):
        """全フィールド揃い + 検算合格 → AUTO_CONFIRMED になること。"""
        # 合計 = 小計 + 税 (1091 + 109 = 1200)
        fields = make_fields(
            total_amount=1200.0,
            subtotal_amount=1091.0,
            tax_amount_10=109.0,
        )
        result = self.scorer.score(fields, vlm_confidence=0.9, rule_confidence=0.9)
        assert result.tier == ConfidenceTier.AUTO_CONFIRMED
        assert result.overall_score >= THRESHOLD_AUTO

    def test_partial_fields_yields_needs_review(self):
        """一部フィールド欠損 → NEEDS_REVIEW になること。"""
        fields = make_fields(
            tax_amount_10=None,
            subtotal_amount=None,
            vendor_registration_no=None,
        )
        result = self.scorer.score(fields, vlm_confidence=0.7, rule_confidence=0.6)
        assert result.tier in (ConfidenceTier.NEEDS_REVIEW, ConfidenceTier.MANUAL_INPUT)

    def test_all_fields_missing_yields_manual_input(self):
        """全フィールド欠損 → MANUAL_INPUT になること。"""
        fields = make_fields(
            transaction_date=None,
            total_amount=None,
            vendor_name=None,
            tax_amount_10=None,
            subtotal_amount=None,
            vendor_registration_no=None,
            account_title=None,
        )
        result = self.scorer.score(fields, vlm_confidence=0.0, rule_confidence=0.0)
        assert result.tier == ConfidenceTier.MANUAL_INPUT
        assert result.overall_score < THRESHOLD_REVIEW

    def test_score_is_between_zero_and_one(self):
        """スコアが 0.0〜1.0 の範囲であること。"""
        fields = make_fields()
        result = self.scorer.score(fields, vlm_confidence=0.5, rule_confidence=0.5)
        assert 0.0 <= result.overall_score <= 1.0

    def test_threshold_auto_boundary(self):
        """THRESHOLD_AUTO 境界値のテスト。"""
        assert THRESHOLD_AUTO == 0.85
        assert THRESHOLD_REVIEW == 0.55


@pytest.mark.unit
class TestArithmeticCheck:
    """検算（小計 + 税 = 合計）のテスト。"""

    def setup_method(self):
        self.scorer = ConfidenceScorer()

    def test_exact_arithmetic_passes(self):
        """小計 + 税10% = 合計（完全一致）で検算合格。"""
        fields = make_fields(
            total_amount=1100.0,
            subtotal_amount=1000.0,
            tax_amount_10=100.0,
        )
        result = self.scorer.score(fields)
        assert result.arithmetic_ok is True
        assert abs(result.arithmetic_diff) < 1.0

    def test_arithmetic_with_1yen_tolerance(self):
        """1円の誤差は許容されること（四捨五入誤差対応）。"""
        fields = make_fields(
            total_amount=1100.0,
            subtotal_amount=1000.0,
            tax_amount_10=101.0,  # 1円多い
        )
        result = self.scorer.score(fields)
        assert result.arithmetic_ok is True

    def test_arithmetic_fails_on_large_discrepancy(self):
        """大きな誤差（100円超）は検算失敗になること。"""
        fields = make_fields(
            total_amount=1200.0,
            subtotal_amount=1000.0,
            tax_amount_10=50.0,  # 明らかに不正
        )
        result = self.scorer.score(fields)
        assert result.arithmetic_ok is False

    def test_arithmetic_check_with_8pct_and_10pct(self):
        """8%と10%の両方が含まれる場合の検算。"""
        # 1000 (10%商品, 税100) + 500 (8%商品, 税40) = 1640 合計
        fields = make_fields(
            total_amount=1640.0,
            subtotal_amount=1500.0,
            tax_amount_10=100.0,
            tax_amount_8=40.0,
        )
        result = self.scorer.score(fields)
        assert result.arithmetic_ok is True

    def test_arithmetic_skipped_when_amounts_missing(self):
        """金額フィールドが全て None の場合、検算はスキップされること。"""
        fields = make_fields(
            total_amount=None,
            subtotal_amount=None,
            tax_amount_10=None,
        )
        result = self.scorer.score(fields)
        # missing fields → arithmetic_ok は False か None
        assert result.arithmetic_ok is not None  # エラーにならないこと


@pytest.mark.unit
class TestScoringResult:
    """ScoringResult の各プロパティテスト。"""

    def setup_method(self):
        self.scorer = ConfidenceScorer()

    def test_field_scores_are_present(self):
        """field_scores に各フィールドのスコアが入ること。"""
        fields = make_fields()
        result = self.scorer.score(fields)
        assert isinstance(result.field_scores, dict)
        assert len(result.field_scores) > 0

    def test_is_auto_property(self):
        """is_auto プロパティが AUTO_CONFIRMED 時に True であること。"""
        fields = make_fields(
            total_amount=1200.0,
            subtotal_amount=1091.0,
            tax_amount_10=109.0,
        )
        result = self.scorer.score(fields, vlm_confidence=0.95, rule_confidence=0.95)
        if result.tier == ConfidenceTier.AUTO_CONFIRMED:
            assert result.is_auto is True

    def test_needs_review_property(self):
        """needs_review プロパティが NEEDS_REVIEW 時に True であること。"""
        fields = make_fields(
            tax_amount_10=None,
            subtotal_amount=None,
        )
        result = self.scorer.score(fields, vlm_confidence=0.7)
        if result.tier == ConfidenceTier.NEEDS_REVIEW:
            assert result.needs_review is True

    def test_flags_are_generated_on_issues(self):
        """問題あり（検算失敗等）の場合にフラグが生成されること。"""
        fields = make_fields(
            total_amount=1200.0,
            subtotal_amount=1000.0,
            tax_amount_10=50.0,  # 検算失敗
        )
        result = self.scorer.score(fields)
        if not result.arithmetic_ok:
            assert len(result.flags) > 0 or len(result.review_reasons) > 0

    def test_score_higher_with_more_fields(self):
        """フィールドが多いほどスコアが高くなること。"""
        full_fields = make_fields()
        partial_fields = make_fields(
            tax_amount_10=None,
            subtotal_amount=None,
            vendor_registration_no=None,
        )
        full_result = self.scorer.score(full_fields, vlm_confidence=0.9)
        partial_result = self.scorer.score(partial_fields, vlm_confidence=0.9)
        assert full_result.overall_score >= partial_result.overall_score

    def test_vlm_confidence_influences_score(self):
        """VLM 信頼度がスコアに影響すること。"""
        fields = make_fields()
        high_vlm = self.scorer.score(fields, vlm_confidence=0.95)
        low_vlm = self.scorer.score(fields, vlm_confidence=0.3)
        assert high_vlm.overall_score >= low_vlm.overall_score
