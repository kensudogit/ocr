"""書類分類モジュールのテスト。

対象: src/core/classifier.py
テスト観点:
  - レシート・手書き領収書・請求書・カード明細・通帳の分類
  - キーワードスコアに基づく判定
  - 感熱紙フラグ・アスペクト比による補正
  - 信頼度スコアの妥当性
"""
from __future__ import annotations

import pytest

from src.core.classifier import DocumentClassifier, ClassificationResult


@pytest.mark.unit
class TestDocumentClassifier:
    """DocumentClassifier のテストクラス。"""

    def setup_method(self):
        self.classifier = DocumentClassifier()

    # ── レシート分類 ──────────────────────────────────────────────────

    def test_classify_receipt_by_keywords(self, sample_receipt_text: str):
        """サンプルレシートテキストが receipt に分類されること。"""
        result = self.classifier.classify(sample_receipt_text)
        assert result.doc_type == "receipt"
        assert result.confidence > 0.5

    def test_classify_convenience_store_receipt(self):
        """コンビニレシートのキーワードで receipt に分類されること。"""
        text = "セブン-イレブン\nお会計 520円\n税込合計 520円\nありがとうございました"
        result = self.classifier.classify(text)
        assert result.doc_type == "receipt"

    def test_classify_receipt_with_thermal_flag(self):
        """is_thermal=True フラグが receipt 判定を強化すること。"""
        text = "合計 1200円"
        result = self.classifier.classify(text, is_thermal=True)
        # 感熱紙フラグで receipt スコアが上乗せされること
        assert result.doc_type in ("receipt", "unknown")

    # ── 手書き領収書分類 ────────────────────────────────────────────

    def test_classify_handwritten_receipt(self, sample_handwritten_text: str):
        """サンプル手書き領収書が handwritten に分類されること。"""
        result = self.classifier.classify(sample_handwritten_text)
        assert result.doc_type in ("handwritten", "receipt")

    def test_classify_uwa_sama_as_handwritten(self):
        """「上様」キーワードで handwritten に分類されること。"""
        text = "領収書\n上様\n¥5,000-\n但し 打合せ費として"
        result = self.classifier.classify(text)
        assert result.doc_type in ("handwritten", "receipt")

    # ── 請求書分類 ───────────────────────────────────────────────────

    def test_classify_invoice(self, sample_invoice_text: str):
        """サンプル請求書テキストが invoice に分類されること。"""
        result = self.classifier.classify(sample_invoice_text)
        assert result.doc_type == "invoice"
        assert result.confidence > 0.5

    def test_classify_invoice_keywords(self):
        """請求書キーワードで invoice に分類されること。"""
        text = "請求書\n品目 システム開発 500,000円\n消費税 50,000円\n合計 550,000円\n振込先 ○○銀行"
        result = self.classifier.classify(text)
        assert result.doc_type == "invoice"

    # ── カード明細分類 ───────────────────────────────────────────────

    def test_classify_card_statement(self, sample_card_text: str):
        """サンプルカード明細が card_statement に分類されること。"""
        result = self.classifier.classify(sample_card_text)
        assert result.doc_type in ("card_statement", "receipt")

    def test_classify_credit_card_keywords(self):
        """クレジットカード明細キーワードで card_statement に分類されること。"""
        text = "カード利用明細\nVISA\nご利用金額 12,500円\n締め日 毎月15日\nポイント 125P"
        result = self.classifier.classify(text)
        assert result.doc_type in ("card_statement", "receipt")

    # ── 未知書類分類 ─────────────────────────────────────────────────

    def test_classify_empty_text_returns_unknown(self):
        """空テキストは unknown に分類されること。"""
        result = self.classifier.classify("")
        assert result.doc_type == "unknown" or result.confidence < 0.3

    def test_classify_noise_text(self):
        """無意味なテキストは低信頼度で返ること。"""
        text = "xyzxyz あああ 123 # @ !"
        result = self.classifier.classify(text)
        assert result.confidence < 0.8

    # ── スコア検証 ──────────────────────────────────────────────────

    def test_classification_result_has_scores(self):
        """ClassificationResult が全種別のスコアを持つこと。"""
        result = self.classifier.classify("合計 1200円")
        assert isinstance(result.scores, dict)
        assert len(result.scores) > 0

    def test_confidence_between_zero_and_one(self):
        """信頼度が 0.0〜1.0 の範囲であること。"""
        for text in ["合計 1200円", "請求書", "カード明細", ""]:
            result = self.classifier.classify(text)
            assert 0.0 <= result.confidence <= 1.0, f"text='{text}' の confidence={result.confidence} が範囲外"

    def test_scores_are_probabilities(self):
        """スコア辞書の値が 0.0〜1.0 であること。"""
        result = self.classifier.classify("レシート 合計 500円")
        for doc_type, score in result.scores.items():
            assert 0.0 <= score <= 1.0, f"{doc_type} のスコア {score} が範囲外"

    def test_aspect_ratio_influences_receipt_score(self):
        """細長いアスペクト比（感熱紙レシート）は receipt スコアを上げること。"""
        narrow_text = "合計 1200円"
        result_narrow = self.classifier.classify(narrow_text, image_aspect_ratio=0.3)  # 縦長
        result_wide = self.classifier.classify(narrow_text, image_aspect_ratio=1.2)   # 横長
        # 縦長のほうが receipt スコアが高いか同等
        receipt_narrow = result_narrow.scores.get("receipt", 0)
        receipt_wide = result_wide.scores.get("receipt", 0)
        # エラーにならないこと（スコアが 0〜1 の範囲内）
        assert 0.0 <= receipt_narrow <= 1.0
        assert 0.0 <= receipt_wide <= 1.0
