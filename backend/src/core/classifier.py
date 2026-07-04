"""書類分類モジュール。

OCR テキストと画像の特徴から書類種別を推定する。

書類種別:
  - receipt       : レシート（感熱紙・POS レジ出力）
  - handwritten   : 手書き領収書
  - invoice       : 請求書（A4 印刷）
  - card_statement: クレジットカード・銀行カード明細
  - bank_statement: 通帳・銀行明細
  - unknown       : 判定不能
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ClassificationResult:
    """書類分類の結果。"""
    doc_type: str
    confidence: float
    scores: dict[str, float]  # 各種別のスコア（合計1.0）


# ── 種別判定キーワード ────────────────────────────────────────────
_KEYWORDS: dict[str, list[str]] = {
    "receipt": [
        "レシート", "領収証", "receipt", "RECEIPT",
        "お買い上げ", "ありがとうございました",
        "税込合計", "税抜合計", "お会計", "税込",
        "小計", "点", "割引",
        "Suica", "PayPay", "iD", "Tポイント",
        "円引", "OFF",
        "レシートNO", "レシートNo", "レシートno",
        "お客様番号", "登録番号",        # 適格請求書登録番号はレシートに表示
    ],
    "handwritten": [
        "領収書", "上様", "但し", "金額", "收入印紙",
        "収入印紙", "印紙", "担当者",
    ],
    "invoice": [
        "請求書", "御請求書", "請求金額", "支払期日", "振込先",
        "銀行口座", "口座番号", "品目", "数量", "単価",
        # 「小計」「消費税」「合計」はレシートにも出現するため除外
        "下記の通り", "適格請求書発行事業者",
        "適格請求書", "インボイス番号", "請求書番号",
    ],
    "card_statement": [
        "カード明細", "利用明細", "クレジット", "ご利用金額",
        "支払日", "締め日", "ポイント", "VISA", "Mastercard",
        "JCB", "AMEX", "お引き落とし金額",
    ],
    "bank_statement": [
        "預金通帳", "口座明細", "残高", "入金", "出金",
        "振込", "引落", "ATM", "普通預金", "当座預金",
    ],
}

# ── 除外ワード（誤判定防止） ─────────────────────────────────────
_NEGATIVE_KEYWORDS: dict[str, list[str]] = {
    "receipt": ["請求書", "振込先", "支払期日"],
    "invoice": ["お買い上げ", "レシート"],
}


class DocumentClassifier:
    """書類種別分類クラス。

    使い方:
        clf = DocumentClassifier()
        result = clf.classify(text, is_thermal=True)
        print(result.doc_type)  # "receipt"
    """

    def classify(
        self,
        text: str,
        is_thermal: bool = False,
        image_aspect_ratio: float | None = None,
    ) -> ClassificationResult:
        """OCR テキストと画像属性から書類種別を推定する。

        Args:
            text:                OCR テキスト
            is_thermal:          感熱紙前処理で検出された場合 True
            image_aspect_ratio:  画像の縦横比 (height / width)。縦長なら invoice の可能性大

        Returns:
            ClassificationResult: 分類結果と信頼度
        """
        text_lower = text.lower()
        scores: dict[str, float] = {t: 0.0 for t in _KEYWORDS}

        # ── キーワードスコアリング ──────────────────────────────
        for doc_type, keywords in _KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    scores[doc_type] += 1.0
            # ネガティブキーワードで減点
            for neg_kw in _NEGATIVE_KEYWORDS.get(doc_type, []):
                if neg_kw.lower() in text_lower:
                    scores[doc_type] -= 2.0

        # ── 画像特性によるブースト ──────────────────────────────
        if is_thermal:
            scores["receipt"] += 3.0

        if image_aspect_ratio is not None:
            if image_aspect_ratio > 1.8:
                # 縦長 = レシート or 通帳の可能性
                scores["receipt"] += 1.0
                scores["bank_statement"] += 0.5
            elif 1.2 <= image_aspect_ratio <= 1.6:
                # A4 縦向き = 請求書の可能性
                scores["invoice"] += 1.5

        # ── 適格請求書番号の有無（T+13桁） ─────────────────────
        # 注意: 登録番号 T+13 はレシート・請求書どちらにも出現する。
        # 「振込先」や「支払期日」など請求書固有キーワードと組み合わさった
        # 場合のみ invoice スコアを加算し、単独での過検知を防ぐ。
        if re.search(r"T\d{13}", text):
            if scores["invoice"] > 0:
                scores["invoice"] += 1.0  # 既に invoice 寄りのときのみ補強

        # ── 手書き判定（OCR 信頼度は呼び出し元で判断） ──────────
        # 手書き特有のキーワードが含まれる場合
        hw_score = scores.get("handwritten", 0.0)
        if hw_score > 0:
            # 「領収書」単独で手書きと断定するのは危険なので
            # 他の印刷書類キーワードがなければ手書きと判定
            if scores["invoice"] < 1.0 and scores["receipt"] < 2.0:
                scores["handwritten"] += 1.5

        # ── 正規化してソフトマックス近似 ───────────────────────
        max_score = max(scores.values()) if scores else 0.0
        if max_score <= 0:
            return ClassificationResult(
                doc_type="unknown",
                confidence=0.0,
                scores=scores,
            )

        best_type = max(scores, key=scores.__getitem__)
        best_score = scores[best_type]

        # 信頼度 = best_score / (best_score + 2番目のスコア)
        sorted_scores = sorted(scores.values(), reverse=True)
        second = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
        confidence = best_score / (best_score + second + 1e-6)
        confidence = min(1.0, max(0.0, confidence))

        # スコアが低すぎる場合は unknown
        if best_score < 1.0:
            best_type = "unknown"
            confidence = 0.2

        return ClassificationResult(
            doc_type=best_type,
            confidence=confidence,
            scores=scores,
        )

    def classify_from_keywords_only(self, text: str) -> str:
        """簡易分類（信頼度不要な場合）。"""
        return self.classify(text).doc_type
