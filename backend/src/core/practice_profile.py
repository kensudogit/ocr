"""地方中規模税理士事務所向け実務プロファイル。

想定ユーザー:
  - 記帳代行を含む税理士事務所（実務担当 約9名）
  - 月500枚以上（2〜3月は確定申告期で増加）
  - 感熱紙レシート / 手書き領収書 / 請求書 / カード明細（サイズ・皺ばらつき）
  - 顧問先の機密財務情報 → 高セキュリティ要件
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.core.preprocessor import PreprocessResult

# 月間処理量の目安（UI・バッチ上限の根拠）
MONTHLY_DOC_TARGET = 500
PEAK_SEASON_MONTHS = (2, 3)  # 確定申告期

# 書類種別（classifier / models と一致）
DOC_RECEIPT = "receipt"
DOC_HANDWRITTEN = "handwritten"
DOC_INVOICE = "invoice"
DOC_CARD = "card_statement"
DOC_BANK = "bank_statement"


@dataclass(frozen=True)
class OpenCvDocProfile:
    """書類種別ごとの OpenCV 前処理パラメータ。"""

    clahe_clip_limit: float
    denoise_strength: int
    adaptive_block_size: int
    adaptive_c: int
    use_binarization: bool
    wrinkle_morph_close: bool


# 税理士事務所で多い書類に最適化した前処理プリセット
DOC_PREPROCESS_PROFILES: dict[str, OpenCvDocProfile] = {
    DOC_RECEIPT: OpenCvDocProfile(
        clahe_clip_limit=3.5,
        denoise_strength=8,
        adaptive_block_size=25,
        adaptive_c=8,
        use_binarization=True,
        wrinkle_morph_close=True,
    ),
    DOC_HANDWRITTEN: OpenCvDocProfile(
        clahe_clip_limit=2.0,
        denoise_strength=6,
        adaptive_block_size=31,
        adaptive_c=12,
        use_binarization=False,  # 手書きはグレースケールのまま OCR 精度を優先
        wrinkle_morph_close=True,
    ),
    DOC_INVOICE: OpenCvDocProfile(
        clahe_clip_limit=2.0,
        denoise_strength=10,
        adaptive_block_size=31,
        adaptive_c=10,
        use_binarization=True,
        wrinkle_morph_close=False,
    ),
    DOC_CARD: OpenCvDocProfile(
        clahe_clip_limit=2.5,
        denoise_strength=12,
        adaptive_block_size=35,
        adaptive_c=10,
        use_binarization=True,
        wrinkle_morph_close=True,
    ),
    DOC_BANK: OpenCvDocProfile(
        clahe_clip_limit=2.5,
        denoise_strength=10,
        adaptive_block_size=31,
        adaptive_c=10,
        use_binarization=True,
        wrinkle_morph_close=True,
    ),
}

DEFAULT_PROFILE = DOC_PREPROCESS_PROFILES[DOC_INVOICE]


def is_peak_season(today: date | None = None) -> bool:
    """確定申告期（2〜3月）かどうか。"""
    d = today or date.today()
    return d.month in PEAK_SEASON_MONTHS


def effective_batch_concurrency(
    base: int,
    peak: int,
    today: date | None = None,
) -> int:
    """通常月 / 繁忙期に応じたバッチ並列数。"""
    return peak if is_peak_season(today) else base


def preprocess_profile_for(doc_type: str | None) -> OpenCvDocProfile:
    """書類種別に応じた前処理プロファイルを返す。"""
    if not doc_type:
        return DEFAULT_PROFILE
    return DOC_PREPROCESS_PROFILES.get(doc_type, DEFAULT_PROFILE)


def estimate_doc_type_from_image(prep: PreprocessResult) -> tuple[str, float]:
    """OCR 前の画像特徴から書類種別を推定（サイズ・感熱紙・縦横比）。

    Returns:
        (doc_type, confidence)
    """
    h, w = prep.final_size
    if w <= 0:
        return "unknown", 0.0

    aspect = h / w
    scores: dict[str, float] = {
        DOC_RECEIPT: 0.0,
        DOC_HANDWRITTEN: 0.0,
        DOC_INVOICE: 0.0,
        DOC_CARD: 0.0,
        DOC_BANK: 0.0,
    }

    if prep.is_thermal_paper:
        scores[DOC_RECEIPT] += 4.0

    if aspect > 2.0:
        scores[DOC_RECEIPT] += 2.5
        scores[DOC_BANK] += 1.0
    elif aspect > 1.5:
        scores[DOC_RECEIPT] += 1.5
        scores[DOC_HANDWRITTEN] += 0.5
    elif 1.15 <= aspect <= 1.45:
        scores[DOC_INVOICE] += 2.5
        scores[DOC_CARD] += 1.5
    elif aspect < 0.85:
        scores[DOC_CARD] += 2.0

    # 低コントラスト・皺っぽい画像は手書き領収書の可能性
    if prep.confidence < 0.55 and not prep.is_thermal_paper:
        scores[DOC_HANDWRITTEN] += 1.5

    max_score = max(scores.values())
    if max_score <= 0:
        return "unknown", 0.0

    best = max(scores, key=scores.__getitem__)
    sorted_vals = sorted(scores.values(), reverse=True)
    second = sorted_vals[1] if len(sorted_vals) > 1 else 0.0
    confidence = min(1.0, best / (best + second + 1e-6))
    return best, confidence


def openai_context_for_doc_type(doc_type: str | None) -> str:
    """OpenAI 後処理用の書類種別コンテキスト。"""
    hints = {
        DOC_RECEIPT: (
            "感熱紙レシート。店名・日時・税込合計・登録番号(T+13)を優先。"
            "薄い文字は OCR テキストの行位置を手がかりに復元。"
        ),
        DOC_HANDWRITTEN: (
            "手書き領収書。金額・日付・但し書き・宛名を慎重に読む。"
            "判読不能な文字は null。推測で補完しない。"
        ),
        DOC_INVOICE: (
            "請求書(A4)。振込先・支払期日・品目明細・適格請求書番号を確認。"
            "小計+消費税=合計の検算を必ず実施。"
        ),
        DOC_CARD: (
            "カード利用明細。利用日・加盟店名・利用金額・締め日を抽出。"
            "複数行ある場合は合計行を優先。"
        ),
        DOC_BANK: (
            "通帳・銀行明細。入出金日・摘要・金額を抽出。"
        ),
    }
    return hints.get(doc_type or "", "一般的な経費書類。")


def should_force_review(doc_type: str | None) -> bool:
    """自動承認を避けるべき書類種別（機密・誤読リスク）。"""
    return doc_type in (DOC_HANDWRITTEN, DOC_CARD, DOC_BANK)
