"""データ抽出モジュール。

OCR テキストから以下の仕訳データを抽出する:
  - 取引日付（令和・平成・西暦・スラッシュ・ドット区切り対応）
  - 店舗名・取引先名
  - 合計金額・税抜金額・消費税額（10% / 8%）
  - 適格請求書発行事業者番号（T + 13桁）
  - 請求書番号
  - 支払方法
  - 品目リスト（明細行）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, date

logger = logging.getLogger(__name__)

# ── 日付パターン（日本語書類に出現する主要フォーマット） ─────────────
_DATE_PATTERNS: list[tuple[str, str]] = [
    # 令和・平成・昭和
    (r"令和\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", "reiwa"),
    (r"平成\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", "heisei"),
    (r"昭和\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", "showa"),
    # 西暦4桁
    (r"(20\d{2})\s*[年/\-\.]\s*(\d{1,2})\s*[月/\-\.]\s*(\d{1,2})\s*日?", "gregorian"),
    # 西暦2桁スラッシュ
    (r"(\d{2})[/\-\.](\d{1,2})[/\-\.](\d{1,2})", "short_gregorian"),
    # 月日のみ（年は当年を補完）
    (r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", "month_day_only"),
]

# ── 金額パターン ─────────────────────────────────────────────────
_AMOUNT_PATTERNS: list[tuple[str, str]] = [
    (r"(?:合計|お会計|総合計|小計\s*合計|請求金額|ご請求金額|お支払い?金額|合計金額)[^\d\n]*¥?\s*([\d,，]+)", "total"),
    (r"(?:税込(?:合計)?|税込金額)[^\d\n]*¥?\s*([\d,，]+)", "total_tax_included"),
    (r"(?:税抜(?:合計)?|税抜金額|本体価格|本体金額|小計)[^\d\n]*¥?\s*([\d,，]+)", "subtotal"),
    (r"(?:消費税(?:額)?|税額)\s*(?:\(10%\)|10%|（10%）)[^\d\n]*¥?\s*([\d,，]+)", "tax_10"),
    (r"(?:消費税(?:額)?|税額)\s*(?:\(8%\)|8%|（8%）)[^\d\n]*¥?\s*([\d,，]+)", "tax_8"),
    (r"(?:消費税(?:額)?|内消費税|税)[^\d\n]*¥?\s*([\d,，]+)", "tax_total"),
    # 最後の ¥ 付き金額（合計の可能性が高い）
    (r"¥\s*([\d,，]+)", "yen_amount"),
]

# ── 適格請求書番号（インボイス番号） ──────────────────────────────
_INVOICE_REG_NO_PATTERN = re.compile(r"T\s*(\d{13})", re.IGNORECASE)
_INVOICE_NO_PATTERN = re.compile(
    r"(?:請求書?番号|No\.?|番号)[^\d\n]*([A-Z0-9\-\/]{3,30})", re.IGNORECASE
)

# ── 支払方法 ─────────────────────────────────────────────────────
_PAYMENT_KEYWORDS: dict[str, list[str]] = {
    "現金":   ["現金", "CASH", "cash"],
    "クレジットカード": ["カード", "クレジット", "VISA", "Mastercard", "AMEX", "JCB"],
    "電子マネー": ["Suica", "PASMO", "iD", "楽天Edy", "nanaco", "WAON", "PayPay", "LINE Pay"],
    "銀行振込": ["振込", "振り込み", "ATM", "銀行"],
    "口座引落": ["口座引落", "自動引落", "口座振替"],
}

# ── 勘定科目キーワードマッピング（簡易） ──────────────────────────
_ACCOUNT_TITLE_MAP: dict[str, list[str]] = {
    "旅費交通費": ["電車", "バス", "タクシー", "新幹線", "高速道路", "駐車場", "航空"],
    "交際費":    ["ホテル", "レストラン", "居酒屋", "接待", "食事", "ラウンジ"],
    "消耗品費":  ["文具", "コンビニ", "100均", "文房具", "オフィス用品"],
    "通信費":    ["NTT", "ドコモ", "au", "ソフトバンク", "インターネット", "電話"],
    "水道光熱費": ["電気", "ガス", "水道"],
    "会議費":    ["会議", "ミーティング", "打ち合わせ", "コーヒー", "カフェ"],
    "新聞図書費": ["書店", "コンビニ", "新聞", "本", "雑誌"],
    "福利厚生費": ["薬局", "ドラッグストア", "クリニック"],
}


@dataclass
class ExtractedFields:
    """抽出フィールドの集約。"""
    transaction_date: datetime | None = None
    vendor_name: str | None = None
    vendor_address: str | None = None
    vendor_phone: str | None = None
    vendor_registration_no: str | None = None  # 適格請求書番号

    total_amount: float | None = None
    subtotal_amount: float | None = None
    tax_amount_10: float | None = None
    tax_amount_8: float | None = None

    invoice_number: str | None = None
    payment_method: str | None = None
    note: str | None = None

    # 推定勘定科目
    account_title: str | None = None

    # 明細行
    line_items: list[dict] = field(default_factory=list)
    # 例: [{"description": "弁当", "quantity": 2, "unit_price": 580, "amount": 1160, "tax_rate": 0.08}]

    # 信頼度スコア（フィールド別）
    confidence: dict[str, float] = field(default_factory=dict)


class DataExtractor:
    """OCR テキストから仕訳データを抽出するクラス。

    使い方:
        extractor = DataExtractor()
        fields = extractor.extract(ocr_text, doc_type="receipt")
    """

    def extract(
        self,
        text: str,
        doc_type: str | None = None,
        ocr_words: list | None = None,
    ) -> ExtractedFields:
        """OCR テキストから仕訳データを抽出する。

        Args:
            text:      OCR 認識テキスト（改行区切り）
            doc_type:  書類種別ヒント
            ocr_words: 単語レベルの認識結果（位置情報付き）

        Returns:
            ExtractedFields: 抽出した仕訳データ
        """
        # 全角→半角変換で正規表現の精度を上げる
        text_norm = self._normalize_text(text)

        result = ExtractedFields()

        result.transaction_date = self._extract_date(text_norm)
        result.vendor_name      = self._extract_vendor_name(text_norm)
        result.vendor_phone     = self._extract_phone(text_norm)
        result.vendor_address   = self._extract_address(text_norm)
        result.vendor_registration_no = self._extract_registration_no(text_norm)
        result.invoice_number   = self._extract_invoice_number(text_norm)
        result.payment_method   = self._extract_payment_method(text_norm)

        amounts = self._extract_amounts(text_norm)
        result.total_amount     = amounts.get("total")
        result.subtotal_amount  = amounts.get("subtotal")
        result.tax_amount_10    = amounts.get("tax_10")
        result.tax_amount_8     = amounts.get("tax_8")

        # 消費税が不明な場合、合計と小計の差から推算
        if result.total_amount and result.subtotal_amount:
            tax_diff = result.total_amount - result.subtotal_amount
            if tax_diff > 0 and result.tax_amount_10 is None and result.tax_amount_8 is None:
                result.tax_amount_10 = tax_diff

        result.line_items       = self._extract_line_items(text_norm)
        result.account_title    = self._suggest_account_title(text_norm, result.vendor_name)
        result.confidence       = self._compute_confidence(result)

        return result

    # ──────────────────────────────────────────────────────────────
    # 各フィールド抽出
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_text(text: str) -> str:
        """全角数字・英字を半角に変換し、OCR エラーを補正する。"""
        try:
            import jaconv
            text = jaconv.z2h(text, kana=False, digit=True, ascii=True)
        except ImportError:
            # jaconv がない場合は簡易変換
            table = str.maketrans(
                "０１２３４５６７８９．，",
                "0123456789.,",
            )
            text = text.translate(table)
        # よくある OCR 誤認識を補正
        corrections = [
            ("¥", "¥"), ("円", "円"),  # 通貨記号の正規化
            ("\u3000", " "),           # 全角スペース→半角
        ]
        for old, new in corrections:
            text = text.replace(old, new)
        return text

    @staticmethod
    def _extract_date(text: str) -> datetime | None:
        """日付を抽出する。複数パターンに対応。"""
        ERA_OFFSETS = {
            "reiwa": 2018,   # 令和1年 = 2019年
            "heisei": 1988,  # 平成1年 = 1989年
            "showa": 1925,   # 昭和1年 = 1926年
        }
        today = datetime.today()

        for pattern, era in _DATE_PATTERNS:
            m = re.search(pattern, text)
            if not m:
                continue
            try:
                groups = m.groups()
                if era in ERA_OFFSETS:
                    year = ERA_OFFSETS[era] + int(groups[0])
                    month, day = int(groups[1]), int(groups[2])
                elif era == "gregorian":
                    year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                elif era == "short_gregorian":
                    year = 2000 + int(groups[0])
                    month, day = int(groups[1]), int(groups[2])
                elif era == "month_day_only":
                    year = today.year
                    month, day = int(groups[0]), int(groups[1])
                    # 未来の日付は前年と判断
                    candidate = date(year, month, day)
                    if candidate > today.date():
                        year -= 1
                else:
                    continue

                return datetime(year, month, day)
            except (ValueError, IndexError):
                continue
        return None

    @staticmethod
    def _extract_vendor_name(text: str) -> str | None:
        """店舗名・取引先名を抽出する。

        ヒューリスティック:
        - 最初の「株式会社」「㈱」「有限会社」等の前後
        - 最初の数行にある会社名らしい文字列
        - 「発行元」「店舗名」等のラベル後の文字列
        """
        lines = text.splitlines()

        # ラベル付きパターン
        patterns = [
            r"(?:発行元|店舗名|取引先|請求元|会社名)[：:]\s*(.+)",
            r"(?:㈱|株式会社|有限会社|合同会社|一般社団法人|公益財団法人)\s*(.{1,30})",
            r"(.{1,30})\s*(?:㈱|株式会社|有限会社|合同会社)",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1).strip()[:100]

        # 先頭付近の非数字行（2行目以降が会社名の可能性）
        for line in lines[:5]:
            line = line.strip()
            if (
                len(line) >= 2
                and not re.match(r"^\d", line)
                and not re.search(r"^\s*[〒\d]", line)
                and "年" not in line and "月" not in line
                and "合計" not in line and "小計" not in line
                and "¥" not in line
            ):
                return line[:100]
        return None

    @staticmethod
    def _extract_phone(text: str) -> str | None:
        """電話番号を抽出する。"""
        m = re.search(r"(?:TEL|Tel|電話|℡)?[\s:：]*(\d{2,4}[-\-]\d{2,4}[-\-]\d{3,4})", text)
        return m.group(1) if m else None

    @staticmethod
    def _extract_address(text: str) -> str | None:
        """住所を抽出する（郵便番号 or 都道府県から始まる行）。"""
        m = re.search(
            r"〒?\s*\d{3}[-\-]\d{4}[^\n]*|"
            r"(?:東京都|大阪府|京都府|北海道|.{2}県).{5,80}",
            text,
        )
        return m.group(0).strip() if m else None

    @staticmethod
    def _extract_registration_no(text: str) -> str | None:
        """適格請求書発行事業者登録番号（T + 13桁）を抽出する。"""
        m = _INVOICE_REG_NO_PATTERN.search(text)
        return f"T{m.group(1)}" if m else None

    @staticmethod
    def _extract_invoice_number(text: str) -> str | None:
        """請求書番号を抽出する。"""
        m = _INVOICE_NO_PATTERN.search(text)
        return m.group(1).strip() if m else None

    @staticmethod
    def _extract_payment_method(text: str) -> str | None:
        """支払方法を抽出する。"""
        for method, keywords in _PAYMENT_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text.lower():
                    return method
        return None

    @staticmethod
    def _extract_amounts(text: str) -> dict[str, float]:
        """合計・小計・消費税金額を抽出する。"""
        results: dict[str, float] = {}

        def parse_amount(s: str) -> float | None:
            s = s.replace(",", "").replace("，", "").replace("¥", "").strip()
            try:
                return float(s)
            except ValueError:
                return None

        for pattern, label in _AMOUNT_PATTERNS:
            m = re.search(pattern, text)
            if not m:
                continue
            val = parse_amount(m.group(1))
            if val is None or val <= 0:
                continue
            # 合計系は total に格納（より具体的なパターンが優先）
            if label in ("total", "total_tax_included") and "total" not in results:
                results["total"] = val
            elif label == "subtotal" and "subtotal" not in results:
                results["subtotal"] = val
            elif label == "tax_10" and "tax_10" not in results:
                results["tax_10"] = val
            elif label == "tax_8" and "tax_8" not in results:
                results["tax_8"] = val
            elif label == "tax_total" and "tax_10" not in results and "tax_8" not in results:
                results["tax_10"] = val  # 税率不明→10%と仮定
            elif label == "yen_amount" and "total" not in results:
                # ¥ 付き金額のうち最大値を合計とみなす
                if val > results.get("_max_yen", 0):
                    results["_max_yen"] = val
                    results["total"] = val

        results.pop("_max_yen", None)
        return results

    @staticmethod
    def _extract_line_items(text: str) -> list[dict]:
        """明細行（品目・数量・単価・金額）を抽出する。

        フォーマット例:
            弁当   2   580   1,160
            コーヒー  1   300    300
        """
        items: list[dict] = []
        # 「品目名 数量 単価 金額」のパターン
        pattern = re.compile(
            r"(.{1,30}?)\s{2,}(\d+)\s*(?:個|本|枚|冊|点|式)?\s+([\d,，]+)\s+([\d,，]+)"
        )
        for m in pattern.finditer(text):
            try:
                description = m.group(1).strip()
                quantity    = int(m.group(2))
                unit_price  = float(m.group(3).replace(",", "").replace("，", ""))
                amount      = float(m.group(4).replace(",", "").replace("，", ""))
                # 整合性チェック（数量 × 単価 ≈ 金額）
                if abs(quantity * unit_price - amount) > amount * 0.1:
                    continue
                items.append({
                    "description": description,
                    "quantity":    quantity,
                    "unit_price":  unit_price,
                    "amount":      amount,
                    "tax_rate":    0.10,  # デフォルト 10%
                })
            except (ValueError, IndexError):
                continue
        return items

    @staticmethod
    def _suggest_account_title(text: str, vendor_name: str | None = None) -> str | None:
        """テキストと店舗名から勘定科目を推定する。"""
        combined = (text + " " + (vendor_name or "")).lower()
        for account, keywords in _ACCOUNT_TITLE_MAP.items():
            if any(kw.lower() in combined for kw in keywords):
                return account
        return None

    @staticmethod
    def _compute_confidence(fields: ExtractedFields) -> dict[str, float]:
        """各フィールドの信頼度スコアを計算する。"""
        return {
            "date":   1.0 if fields.transaction_date else 0.0,
            "amount": 1.0 if fields.total_amount else 0.0,
            "vendor": 0.8 if fields.vendor_name else 0.0,
            "tax":    1.0 if (fields.tax_amount_10 or fields.tax_amount_8) else 0.2,
        }
