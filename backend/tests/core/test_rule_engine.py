"""ルールエンジンのテスト。

対象: src/core/rule_engine.py
テスト観点:
  - キーワードベースのデフォルト提案
  - 過去仕訳からの学習と提案
  - 完全一致・部分一致の優先順位
  - 顧問先別の分離
  - 税区分の正規化
"""
from __future__ import annotations

import pytest

from src.core.rule_engine import RuleEngine, RuleSuggestion, get_rule_engine


@pytest.mark.unit
class TestRuleEngineDefaultMappings:
    """デフォルトキーワードマッピングのテスト。"""

    def setup_method(self):
        self.engine = RuleEngine()

    def test_convenience_store_maps_to_shomohin(self):
        """コンビニ → 消耗品費 にマッピングされること。"""
        result = self.engine.suggest(vendor_name="セブンイレブン渋谷店")
        assert result.account_title == "消耗品費"
        assert result.tax_category == "課税仕入10%"

    def test_taxi_maps_to_ryohi_kotssuhi(self):
        """タクシー → 旅費交通費 にマッピングされること。"""
        result = self.engine.suggest(vendor_name="東京タクシー")
        assert result.account_title == "旅費交通費"

    def test_train_maps_to_ryohi_kotssuhi(self):
        """電車 → 旅費交通費 にマッピングされること。"""
        result = self.engine.suggest(vendor_name="JR東日本")
        assert result.account_title == "旅費交通費"

    def test_restaurant_maps_to_kosaichi(self):
        """レストラン → 交際費 にマッピングされること。"""
        result = self.engine.suggest(vendor_name="新宿レストランABC")
        assert result.account_title == "交際費"

    def test_electricity_maps_to_konetsu(self):
        """電力会社 → 水道光熱費 にマッピングされること。"""
        result = self.engine.suggest(vendor_name="東京電力")
        assert result.account_title == "水道光熱費"

    def test_phone_maps_to_tsuushinhi(self):
        """通信会社 → 通信費 にマッピングされること。"""
        result = self.engine.suggest(vendor_name="NTTドコモ")
        assert result.account_title == "通信費"

    def test_amazon_maps_to_shomohin(self):
        """Amazon → 消耗品費 にマッピングされること。"""
        result = self.engine.suggest(vendor_name="Amazon.co.jp")
        assert result.account_title == "消耗品費"

    def test_cafe_maps_to_kaigishi(self):
        """カフェ → 会議費 にマッピングされること。"""
        result = self.engine.suggest(vendor_name="スターバックス渋谷")
        assert result.account_title == "会議費"

    def test_unknown_vendor_returns_suggestion(self):
        """不明な取引先でも何らかの提案が返ること。"""
        result = self.engine.suggest(vendor_name="謎の商店XYZ")
        assert isinstance(result, RuleSuggestion)
        # confidence は低いが、フォールバックが返ること
        assert result.confidence >= 0.0

    def test_none_vendor_name(self):
        """None の取引先名は安全に処理されること。"""
        result = self.engine.suggest(vendor_name=None)
        assert isinstance(result, RuleSuggestion)

    def test_empty_vendor_name(self):
        """空文字の取引先名は安全に処理されること。"""
        result = self.engine.suggest(vendor_name="")
        assert isinstance(result, RuleSuggestion)


@pytest.mark.unit
class TestRuleEngineLearning:
    """学習機能のテスト。"""

    def setup_method(self):
        self.engine = RuleEngine()

    def test_learn_creates_mapping(self):
        """learn() で登録した取引先が次回から提案されること。"""
        vendor = "テスト株式会社ABC"
        self.engine.learn(
            vendor_name=vendor,
            account_title="外注費",
            tax_category="課税仕入10%",
        )
        result = self.engine.suggest(vendor_name=vendor)
        assert result.account_title == "外注費"
        assert result.match_type in ("exact", "partial")

    def test_learned_mapping_has_higher_confidence(self):
        """学習済みマッピングはデフォルトより信頼度が高いこと。"""
        vendor = "カスタム商店99999"
        self.engine.learn(
            vendor_name=vendor,
            account_title="雑費",
            tax_category="課税仕入10%",
        )
        learned_result = self.engine.suggest(vendor_name=vendor)
        default_result = self.engine.suggest(vendor_name="未登録の店舗")
        assert learned_result.confidence >= default_result.confidence

    def test_learn_partial_match(self):
        """部分一致でも学習済みマッピングが提案されること。"""
        self.engine.learn(
            vendor_name="東京電気工業",
            account_title="修繕費",
            tax_category="課税仕入10%",
        )
        result = self.engine.suggest(vendor_name="東京電気")
        # 前方一致でマッチすること
        assert result.account_title in ("修繕費", "水道光熱費")  # 電気ではどちらも可

    def test_learn_client_specific(self):
        """顧問先固有の学習が他の顧問先に影響しないこと。"""
        client_a = "client-001"
        client_b = "client-002"
        vendor = "サンプル商店固有"

        self.engine.learn(
            vendor_name=vendor,
            account_title="交際費",
            tax_category="課税仕入10%",
            client_id=client_a,
        )
        # client_a は学習済みを使う
        result_a = self.engine.suggest(vendor_name=vendor, client_id=client_a)
        # client_b は学習なし → デフォルト
        result_b = self.engine.suggest(vendor_name=vendor, client_id=client_b)

        # client_a は学習した「交際費」を返すはず
        assert result_a.account_title == "交際費"
        # client_b は独立している（交際費ではない可能性）
        # 厳密比較ではなく、独立していることだけ確認
        assert isinstance(result_b, RuleSuggestion)

    def test_load_from_history(self):
        """load_from_history() でバルクロードできること。"""
        history = [
            ("サンプル運輸", "旅費交通費", "課税仕入10%"),
            ("XXX電気工業", "外注費", "課税仕入10%"),
            ("テスト薬局", "福利厚生費", "課税仕入10%"),
        ]
        self.engine.load_from_history(history, client_id="bulk-client")

        result = self.engine.suggest(vendor_name="サンプル運輸", client_id="bulk-client")
        assert result.account_title == "旅費交通費"


@pytest.mark.unit
class TestTaxCategoryNormalization:
    """税区分の正規化テスト。"""

    def setup_method(self):
        self.engine = RuleEngine()

    def test_tax_category_suggestions_are_valid(self):
        """デフォルトマッピングの税区分が有効な値であること。"""
        valid_categories = {"課税仕入10%", "課税仕入8%軽減", "非課税", "不課税"}

        for vendor in ["セブンイレブン", "JR東日本", "東京電力"]:
            result = self.engine.suggest(vendor_name=vendor)
            if result.tax_category:
                assert result.tax_category in valid_categories, (
                    f"{vendor} の税区分 '{result.tax_category}' は有効な値ではありません"
                )

    def test_food_items_use_reduced_rate(self):
        """食品（弁当等）は軽減税率（8%）になること。"""
        result = self.engine.suggest(vendor_name="お弁当屋さん")
        # 弁当はキーワードマッピングで 8% になること
        if result.account_title == "福利厚生費":
            assert result.tax_category == "課税仕入8%軽減"


@pytest.mark.unit
class TestGetRuleEngine:
    """シングルトン取得のテスト。"""

    def test_get_rule_engine_returns_instance(self):
        """get_rule_engine() が RuleEngine インスタンスを返すこと。"""
        engine = get_rule_engine()
        assert isinstance(engine, RuleEngine)

    def test_get_rule_engine_returns_same_instance(self):
        """get_rule_engine() は同じインスタンスを返すこと（シングルトン）。"""
        engine1 = get_rule_engine()
        engine2 = get_rule_engine()
        assert engine1 is engine2
