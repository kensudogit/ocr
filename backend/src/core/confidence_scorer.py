"""信頼度スコアリング & 3段階自動仕分けモジュール。

判定基準:
  - AUTO_CONFIRMED  (≥ 0.85): 高信頼度 → 担当者確認不要、自動承認
  - NEEDS_REVIEW    (0.55〜0.85): 中信頼度 → 担当者による確認・修正が必要
  - MANUAL_INPUT    (< 0.55): 低信頼度 → ほぼ手入力が必要

検算ロジック:
  小計（税抜）+ 消費税（10%）+ 消費税（8%）≒ 合計（許容誤差 1円 or 0.5%）

各フィールドへのスコア寄与:
  - transaction_date  : 20%
  - total_amount      : 30%
  - vendor_name       : 20%
  - tax_amount        : 15%
  - arithmetic_check  : 15%（検算パス → +0.15、失敗 → 0）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from src.core.extractor import ExtractedFields


class ConfidenceTier(str, Enum):
    """3段階の信頼度区分。"""
    AUTO_CONFIRMED = "auto_confirmed"  # 自動承認
    NEEDS_REVIEW   = "needs_review"    # 要確認
    MANUAL_INPUT   = "manual_input"    # 手入力


@dataclass
class ScoringResult:
    """スコアリング結果。"""
    tier: ConfidenceTier
    overall_score: float          # 0.0〜1.0
    field_scores: dict[str, float]  # フィールド別スコア
    arithmetic_ok: bool           # 検算結果
    arithmetic_diff: float        # 検算誤差（金額）
    flags: list[str] = field(default_factory=list)  # 注意フラグ
    review_reasons: list[str] = field(default_factory=list)  # 要確認理由

    @property
    def is_auto(self) -> bool:
        return self.tier == ConfidenceTier.AUTO_CONFIRMED

    @property
    def needs_review(self) -> bool:
        return self.tier == ConfidenceTier.NEEDS_REVIEW


# ── 閾値 ───────────────────────────────────────────────────────────────
THRESHOLD_AUTO   = 0.85
THRESHOLD_REVIEW = 0.55

# ── フィールド重み ─────────────────────────────────────────────────────
_WEIGHTS = {
    "transaction_date": 0.20,
    "total_amount":     0.30,
    "vendor_name":      0.20,
    "tax_amount":       0.15,
    "arithmetic":       0.15,
}


class ConfidenceScorer:
    """信頼度スコアリングクラス。

    使い方:
        scorer = ConfidenceScorer()
        result = scorer.score(fields, vlm_confidence=0.88, rule_confidence=0.70)
        if result.is_auto:
            # 自動承認
        elif result.needs_review:
            # 確認画面に表示
    """

    def score(
        self,
        fields: ExtractedFields,
        vlm_confidence: float = 0.0,
        rule_confidence: float = 0.0,
        ocr_engine_confidence: float = 0.0,
    ) -> ScoringResult:
        """統合スコアを計算して 3段階に分類する。

        Args:
            fields:                 抽出フィールド
            vlm_confidence:         VLM の全体信頼度
            rule_confidence:        ルールエンジンのマッチ信頼度
            ocr_engine_confidence:  OCR エンジンの信頼度

        Returns:
            ScoringResult: スコア・ティア・フラグ
        """
        field_scores: dict[str, float] = {}
        flags: list[str] = []
        reasons: list[str] = []

        # ── 日付スコア ──────────────────────────────────────────────
        if fields.transaction_date:
            field_scores["transaction_date"] = 1.0
        else:
            field_scores["transaction_date"] = 0.0
            reasons.append("取引日が抽出できませんでした")

        # ── 金額スコア ──────────────────────────────────────────────
        if fields.total_amount and fields.total_amount > 0:
            # 金額の桁数チェック（1円〜1,000万円が通常範囲）
            if 1 <= fields.total_amount <= 10_000_000:
                field_scores["total_amount"] = 1.0
            else:
                field_scores["total_amount"] = 0.5
                flags.append(f"金額が通常範囲外: ¥{fields.total_amount:,.0f}")
        else:
            field_scores["total_amount"] = 0.0
            reasons.append("合計金額が抽出できませんでした")

        # ── 取引先スコア ────────────────────────────────────────────
        if fields.vendor_name and len(fields.vendor_name) >= 2:
            field_scores["vendor_name"] = min(1.0, len(fields.vendor_name) / 20 + 0.5)
        else:
            field_scores["vendor_name"] = 0.0
            reasons.append("取引先名が抽出できませんでした")

        # ── 消費税スコア ────────────────────────────────────────────
        has_tax = (fields.tax_amount_10 or 0) + (fields.tax_amount_8 or 0) > 0
        if has_tax:
            field_scores["tax_amount"] = 1.0
        elif fields.total_amount:
            # 合計金額が既知なら消費税がなくても低スコアで許容
            field_scores["tax_amount"] = 0.3
            reasons.append("消費税額が不明（10%税区分で計算してください）")
        else:
            field_scores["tax_amount"] = 0.0

        # ── 検算 ───────────────────────────────────────────────────
        arithmetic_ok, diff = self._check_arithmetic(fields)
        if arithmetic_ok:
            field_scores["arithmetic"] = 1.0
        else:
            field_scores["arithmetic"] = 0.0
            if diff > 0:
                flags.append(f"検算不一致: 差額 ¥{diff:,.0f}（小計+税≠合計）")
                reasons.append("金額の検算が合いません。手動で確認してください")

        # ── 統合スコア計算 ──────────────────────────────────────────
        # フィールドスコアの加重平均
        base_score = sum(
            field_scores.get(k, 0.0) * w
            for k, w in _WEIGHTS.items()
        )

        # VLM / ルール / OCR の信頼度を補正係数として使用
        engine_score = max(vlm_confidence, ocr_engine_confidence)
        if engine_score > 0:
            # エンジン信頼度でわずかに補正（最大 ±10%）
            adjustment = (engine_score - 0.5) * 0.2
            base_score = min(1.0, max(0.0, base_score + adjustment))

        # ルールエンジンの信頼度も加味
        if rule_confidence >= 0.85:
            base_score = min(1.0, base_score + 0.05)

        overall_score = round(base_score, 3)

        # ── 3段階分類 ──────────────────────────────────────────────
        if overall_score >= THRESHOLD_AUTO and not reasons:
            tier = ConfidenceTier.AUTO_CONFIRMED
        elif overall_score >= THRESHOLD_REVIEW:
            tier = ConfidenceTier.NEEDS_REVIEW
        else:
            tier = ConfidenceTier.MANUAL_INPUT

        # 検算失敗は必ず NEEDS_REVIEW 以上にする
        if not arithmetic_ok and diff > 10 and tier == ConfidenceTier.AUTO_CONFIRMED:
            tier = ConfidenceTier.NEEDS_REVIEW

        return ScoringResult(
            tier=tier,
            overall_score=overall_score,
            field_scores=field_scores,
            arithmetic_ok=arithmetic_ok,
            arithmetic_diff=diff,
            flags=flags,
            review_reasons=reasons,
        )

    @staticmethod
    def _check_arithmetic(fields: ExtractedFields) -> tuple[bool, float]:
        """検算を実施する。

        小計 + 消費税(10%) + 消費税(8%) ≒ 合計（誤差 1円 or 0.5%）

        Returns:
            (ok: bool, diff: float)  — diff は絶対差額
        """
        total = fields.total_amount
        if not total or total <= 0:
            return True, 0.0  # 合計が不明なら検算スキップ

        subtotal = fields.subtotal_amount or 0.0
        tax10    = fields.tax_amount_10 or 0.0
        tax8     = fields.tax_amount_8 or 0.0

        # 消費税のみで計算できる場合
        if subtotal == 0.0 and (tax10 + tax8) == 0.0:
            return True, 0.0  # フィールドが不足 → 検算スキップ

        # パターン 1: 小計 + 税 = 合計
        if subtotal > 0 and (tax10 + tax8) > 0:
            calculated = subtotal + tax10 + tax8
            diff = abs(total - calculated)
            tolerance = max(1.0, total * 0.005)  # 1円 or 0.5%
            return diff <= tolerance, round(diff, 2)

        # パターン 2: 合計と小計の差 = 税合計
        if subtotal > 0:
            implied_tax = total - subtotal
            if implied_tax < 0:
                return False, round(abs(implied_tax), 2)
            # 税率 8% or 10% の妥当性チェック
            expected_tax_10 = round(subtotal * 0.10)
            expected_tax_8  = round(subtotal * 0.08)
            if abs(implied_tax - expected_tax_10) <= max(1.0, total * 0.005):
                return True, 0.0
            if abs(implied_tax - expected_tax_8) <= max(1.0, total * 0.005):
                return True, 0.0
            return False, round(abs(implied_tax - expected_tax_10), 2)

        # パターン 3: 合計と税額のみ（小計不明）
        if (tax10 + tax8) > 0:
            # 合計 × (税率 / (1 + 税率)) ≒ 税額
            expected_tax_10 = round(total * 10 / 110)
            expected_tax_8  = round(total * 8 / 108)
            actual_tax = tax10 + tax8
            if abs(actual_tax - expected_tax_10) <= max(1.0, total * 0.01):
                return True, 0.0
            if abs(actual_tax - expected_tax_8) <= max(1.0, total * 0.01):
                return True, 0.0
            return False, round(abs(actual_tax - expected_tax_10), 2)

        return True, 0.0
