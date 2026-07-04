"""ルールエンジン — 顧問先別の勘定科目・税区分サジェスト。

機能:
  1. 顧問先ごとの「取引先名 → 勘定科目」マッピングを過去仕訳から学習
  2. 新規書類の取引先名と類似する過去仕訳を検索し、勘定科目・税区分を提案
  3. 学習した結果を DB の journal_history テーブルに保存

サジェストロジック:
  - Step 1: 完全一致（取引先名 = 過去の取引先名）
  - Step 2: 前方一致・部分一致
  - Step 3: キーワードベースのデフォルトマッピング（既存 classifier.py 流用）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


# ── キーワードベースのデフォルトマッピング ──────────────────────────────
_DEFAULT_MAPPINGS: list[tuple[list[str], str, str]] = [
    # (キーワードリスト, 勘定科目, 税区分)
    (["コンビニ", "セブン", "ファミマ", "ローソン", "ミニストップ", "ヤマザキ"],
     "消耗品費", "課税仕入10%"),
    (["電車", "バス", "タクシー", "新幹線", "高速", "駐車", "JR", "東京メトロ"],
     "旅費交通費", "課税仕入10%"),
    (["ガソリン", "給油", "石油", "ENEOS", "出光", "昭和シェル"],
     "旅費交通費", "課税仕入10%"),
    (["ホテル", "旅館", "宿泊", "リゾート", "inn"],
     "旅費交通費", "課税仕入10%"),
    (["レストラン", "食堂", "居酒屋", "焼肉", "ラーメン", "すし", "定食"],
     "交際費", "課税仕入10%"),
    (["スーパー", "イオン", "西友", "コープ", "マルエツ"],
     "消耗品費", "課税仕入10%"),
    (["NTT", "ドコモ", "au", "ソフトバンク", "楽天モバイル", "インターネット", "Wi-Fi"],
     "通信費", "課税仕入10%"),
    (["電気", "東京電力", "関西電力", "中部電力"],
     "水道光熱費", "課税仕入10%"),
    (["ガス", "東京ガス", "大阪ガス"],
     "水道光熱費", "課税仕入10%"),
    (["水道"],
     "水道光熱費", "非課税"),
    (["書店", "本", "雑誌", "新聞", "ブック"],
     "新聞図書費", "課税仕入10%"),
    (["薬局", "ドラッグ", "マツキヨ", "ウエルシア", "ツルハ"],
     "福利厚生費", "課税仕入10%"),
    (["文具", "コクヨ", "文房具", "はんこ", "スタンプ"],
     "消耗品費", "課税仕入10%"),
    (["カフェ", "コーヒー", "スタバ", "スターバックス", "ドトール", "タリーズ", "コメダ", "珈琲"],
     "会議費", "課税仕入10%"),
    (["アマゾン", "Amazon", "楽天", "Yahoo"],
     "消耗品費", "課税仕入10%"),
    (["弁当", "惣菜", "デリ"],
     "福利厚生費", "課税仕入8%軽減"),  # 食品は軽減税率
]

# 税区分ラベルの正規化
_TAX_CATEGORY_ALIASES: dict[str, str] = {
    "課税10%":   "課税仕入10%",
    "課税8%":    "課税仕入8%軽減",
    "課税仕入8%": "課税仕入8%軽減",
    "軽減8%":    "課税仕入8%軽減",
    "非課税":    "非課税",
    "不課税":    "不課税",
    "免税":      "不課税",
}


@dataclass
class RuleSuggestion:
    """ルールエンジンによるサジェスト結果。"""
    account_title: str | None
    tax_category: str | None
    match_type: str  # "exact" / "partial" / "keyword" / "none"
    confidence: float  # 0.0〜1.0
    matched_vendor: str | None = None  # マッチした過去の取引先名


class RuleEngine:
    """顧問先別・過去仕訳学習ベースのルールエンジン。

    DB 依存なしでも動作する（メモリキャッシュ使用）。
    DB が接続されている場合は過去仕訳から学習する。
    """

    def __init__(self) -> None:
        # メモリキャッシュ: {client_id: [(vendor_name, account_title, tax_category)]}
        self._cache: dict[str, list[tuple[str, str, str]]] = {}
        # グローバルキャッシュ（client_id なし）
        self._global_cache: list[tuple[str, str, str]] = []

    # ──────────────────────────────────────────────────────────────
    # パブリック API
    # ──────────────────────────────────────────────────────────────

    def suggest(
        self,
        vendor_name: str | None,
        client_id: str | None = None,
        current_account_title: str | None = None,
        current_tax_category: str | None = None,
    ) -> RuleSuggestion:
        """取引先名と顧問先IDから勘定科目・税区分を提案する。

        Args:
            vendor_name:           抽出した取引先名
            client_id:             顧問先ID（Noneの場合はグローバル）
            current_account_title: VLM が既に提案している勘定科目（補強に使用）
            current_tax_category:  VLM が既に提案している税区分（補強に使用）

        Returns:
            RuleSuggestion: 勘定科目・税区分の提案
        """
        if not vendor_name:
            return RuleSuggestion(
                account_title=current_account_title,
                tax_category=current_tax_category,
                match_type="none",
                confidence=0.3,
            )

        vendor_norm = self._normalize(vendor_name)

        # ── Step 1: 顧問先別の完全一致 ────────────────────────────
        client_history = self._cache.get(client_id or "_global", [])
        for past_vendor, account, tax in client_history:
            if self._normalize(past_vendor) == vendor_norm:
                return RuleSuggestion(
                    account_title=account,
                    tax_category=self._normalize_tax(tax),
                    match_type="exact",
                    confidence=0.97,
                    matched_vendor=past_vendor,
                )

        # ── Step 2: 顧問先別の部分一致 ────────────────────────────
        for past_vendor, account, tax in client_history:
            past_norm = self._normalize(past_vendor)
            if past_norm in vendor_norm or vendor_norm in past_norm:
                return RuleSuggestion(
                    account_title=account,
                    tax_category=self._normalize_tax(tax),
                    match_type="partial",
                    confidence=0.85,
                    matched_vendor=past_vendor,
                )

        # ── Step 3: グローバル履歴の完全一致 ──────────────────────
        for past_vendor, account, tax in self._global_cache:
            if self._normalize(past_vendor) == vendor_norm:
                return RuleSuggestion(
                    account_title=account,
                    tax_category=self._normalize_tax(tax),
                    match_type="exact",
                    confidence=0.90,
                    matched_vendor=past_vendor,
                )

        # ── Step 4: キーワードマッチング ──────────────────────────
        for keywords, account, tax in _DEFAULT_MAPPINGS:
            for kw in keywords:
                if kw.lower() in vendor_name.lower():
                    return RuleSuggestion(
                        account_title=account,
                        tax_category=tax,
                        match_type="keyword",
                        confidence=0.70,
                    )

        # ── Step 5: VLM 提案をそのまま採用 ────────────────────────
        if current_account_title:
            return RuleSuggestion(
                account_title=current_account_title,
                tax_category=self._normalize_tax(current_tax_category),
                match_type="vlm",
                confidence=0.60,
            )

        return RuleSuggestion(
            account_title=None,
            tax_category=None,
            match_type="none",
            confidence=0.0,
        )

    def learn(
        self,
        vendor_name: str,
        account_title: str,
        tax_category: str,
        client_id: str | None = None,
    ) -> None:
        """承認済み仕訳からルールを学習する（メモリキャッシュに追加）。

        DB 保存は呼び出し元（API 層）が担当。
        """
        if not vendor_name or not account_title:
            return
        key = client_id or "_global"
        entry = (vendor_name, account_title, self._normalize_tax(tax_category))

        # 重複を避けて先頭に追加（最新の学習を優先）
        cache = self._cache.setdefault(key, [])
        cache = [c for c in cache if self._normalize(c[0]) != self._normalize(vendor_name)]
        cache.insert(0, entry)
        self._cache[key] = cache[:500]  # 最大 500 件

        # グローバルキャッシュにも追加
        self._global_cache = [
            c for c in self._global_cache
            if self._normalize(c[0]) != self._normalize(vendor_name)
        ]
        self._global_cache.insert(0, entry)
        self._global_cache = self._global_cache[:2000]

    def load_from_history(
        self,
        history: list[tuple[str, str, str]],
        client_id: str | None = None,
    ) -> None:
        """DB から取得した過去仕訳履歴をキャッシュに読み込む。

        Args:
            history: [(vendor_name, account_title, tax_category), ...]
        """
        key = client_id or "_global"
        self._cache[key] = [(v, a, t) for v, a, t in history if v and a]
        for v, a, t in history:
            if v and a:
                self._global_cache.append((v, a, t))
        logger.info("ルールエンジン: %d 件の過去仕訳を読み込みました（client=%s）", len(history), client_id)

    # ──────────────────────────────────────────────────────────────
    # ユーティリティ
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(text: str) -> str:
        """テキストを正規化（全角→半角・大文字小文字統一・スペース除去）。"""
        import unicodedata
        text = unicodedata.normalize("NFKC", text)
        return re.sub(r"[\s　]+", "", text).lower()

    @staticmethod
    def _normalize_tax(tax: str | None) -> str | None:
        """税区分ラベルを正規化する。"""
        if not tax:
            return None
        return _TAX_CATEGORY_ALIASES.get(tax, tax)


# シングルトン
_rule_engine = RuleEngine()


def get_rule_engine() -> RuleEngine:
    """グローバルルールエンジンを返す。"""
    return _rule_engine
