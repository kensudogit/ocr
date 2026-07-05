"""practice_profile モジュールのテスト。"""
from __future__ import annotations

from datetime import date

import pytest

from src.core.practice_profile import (
    effective_batch_concurrency,
    estimate_doc_type_from_image,
    is_peak_season,
    openai_context_for_doc_type,
    preprocess_profile_for,
    should_force_review,
)
from src.core.preprocessor import PreprocessResult


class TestPracticeProfile:
    def test_peak_season_feb_mar(self):
        assert is_peak_season(date(2026, 2, 15)) is True
        assert is_peak_season(date(2026, 3, 31)) is True
        assert is_peak_season(date(2026, 4, 1)) is False

    def test_batch_concurrency_increases_in_peak(self):
        assert effective_batch_concurrency(3, 5, date(2026, 2, 1)) == 5
        assert effective_batch_concurrency(3, 5, date(2026, 6, 1)) == 3

    def test_thermal_receipt_image_estimate(self):
        prep = PreprocessResult(
            image=[],
            pil_image=None,  # type: ignore[arg-type]
            final_size=(2400, 800),
            is_thermal_paper=True,
            confidence=0.8,
        )
        doc_type, conf = estimate_doc_type_from_image(prep)
        assert doc_type == "receipt"
        assert conf > 0.5

    def test_invoice_aspect_estimate(self):
        prep = PreprocessResult(
            image=[],
            pil_image=None,  # type: ignore[arg-type]
            final_size=(1400, 1000),
            is_thermal_paper=False,
            confidence=0.9,
        )
        doc_type, _ = estimate_doc_type_from_image(prep)
        assert doc_type == "invoice"

    def test_handwritten_profile_skips_binarization(self):
        profile = preprocess_profile_for("handwritten")
        assert profile.use_binarization is False

    def test_receipt_profile_strong_clahe(self):
        profile = preprocess_profile_for("receipt")
        assert profile.clahe_clip_limit >= 3.0

    def test_openai_context_includes_doc_hint(self):
        ctx = openai_context_for_doc_type("handwritten")
        assert "手書き" in ctx

    def test_should_force_review_handwritten(self):
        assert should_force_review("handwritten") is True
        assert should_force_review("invoice") is False
