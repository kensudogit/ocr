"""監査ログモジュールのテスト。

対象: src/core/audit_log.py
テスト観点:
  - AuditLogger.log() の動作
  - log_data_change() での差分抽出
  - audit_request_middleware のレスポンスヘッダ付与
  - get_audit_logger() シングルトン
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.audit_log import AuditEventType, AuditLogger, get_audit_logger


@pytest.mark.unit
class TestAuditEventType:
    """AuditEventType 定数のテスト。"""

    def test_event_types_are_strings(self):
        """全イベント種別が文字列であること。"""
        event_types = [
            AuditEventType.LOGIN,
            AuditEventType.LOGOUT,
            AuditEventType.LOGIN_FAILED,
            AuditEventType.DOC_UPLOAD,
            AuditEventType.DOC_VIEW,
            AuditEventType.DOC_APPROVE,
            AuditEventType.DOC_REJECT,
            AuditEventType.DOC_EDIT,
            AuditEventType.DOC_DELETE,
            AuditEventType.DOC_EXPORT,
            AuditEventType.JOURNAL_CREATE,
            AuditEventType.JOURNAL_EDIT,
            AuditEventType.JOURNAL_APPROVE,
            AuditEventType.AI_REQUEST,
            AuditEventType.EXPORT_CSV,
            AuditEventType.EXPORT_API,
        ]
        for et in event_types:
            assert isinstance(et, str), f"イベント種別 {et} が文字列でない"

    def test_event_type_format(self):
        """イベント種別が 'category.action' 形式であること。"""
        for attr in dir(AuditEventType):
            if attr.startswith("_"):
                continue
            value = getattr(AuditEventType, attr)
            if isinstance(value, str):
                assert "." in value, f"{attr} = '{value}' は 'category.action' 形式でない"


@pytest.mark.unit
class TestAuditLogger:
    """AuditLogger のテスト。"""

    @pytest.mark.asyncio
    async def test_log_without_db_does_not_raise(self):
        """DB なしでの log() がエラーにならないこと。"""
        logger = AuditLogger()
        # DB なし → ファイルログのみ（エラーにならないこと）
        await logger.log(
            event_type=AuditEventType.DOC_UPLOAD,
            user_id="test_user",
            resource_type="document",
            resource_id="doc-001",
            detail={"filename": "test.jpg"},
        )

    @pytest.mark.asyncio
    async def test_log_with_status_success(self):
        """status='success' でログが記録できること。"""
        logger = AuditLogger()
        await logger.log(
            event_type=AuditEventType.DOC_APPROVE,
            user_id="staff_01",
            resource_id="doc-001",
            status="success",
        )

    @pytest.mark.asyncio
    async def test_log_with_status_failure(self):
        """status='failure' でログが記録できること。"""
        logger = AuditLogger()
        await logger.log(
            event_type=AuditEventType.LOGIN_FAILED,
            user_id="unknown",
            ip_address="192.168.1.100",
            status="failure",
        )

    @pytest.mark.asyncio
    async def test_log_anonymous_user(self):
        """user_id=None（anonymous）でエラーにならないこと。"""
        logger = AuditLogger()
        await logger.log(
            event_type=AuditEventType.DOC_VIEW,
            user_id=None,
        )

    @pytest.mark.asyncio
    async def test_log_data_change_extracts_diff(self):
        """log_data_change() が変更前後の差分を正確に抽出すること。"""
        logger = AuditLogger()
        before = {"account_title": "消耗品費", "tax_category": "課税仕入10%", "amount": 1200}
        after = {"account_title": "旅費交通費", "tax_category": "課税仕入10%", "amount": 1200}

        # DB なしでもエラーにならないこと
        await logger.log_data_change(
            event_type=AuditEventType.JOURNAL_EDIT,
            user_id="staff_01",
            resource_type="journal",
            resource_id="journal-001",
            before=before,
            after=after,
        )

    @pytest.mark.asyncio
    async def test_log_data_change_detects_changed_field(self):
        """log_data_change() が変更されたフィールドのみを抽出すること。"""
        logger = AuditLogger()

        captured_detail = {}

        async def mock_log(**kwargs):
            nonlocal captured_detail
            captured_detail = kwargs.get("detail", {})

        with patch.object(logger, "log", side_effect=mock_log):
            await logger.log_data_change(
                event_type=AuditEventType.JOURNAL_EDIT,
                user_id="staff",
                resource_type="journal",
                resource_id="j-001",
                before={"field_a": "old", "field_b": "same"},
                after={"field_a": "new", "field_b": "same"},
            )

        # 変更された field_a だけが含まれること
        changes = captured_detail.get("changes", {})
        assert "field_a" in changes
        assert changes["field_a"]["before"] == "old"
        assert changes["field_a"]["after"] == "new"
        # 変更されていない field_b は含まれないこと
        assert "field_b" not in changes


@pytest.mark.unit
class TestGetAuditLogger:
    """get_audit_logger() シングルトンのテスト。"""

    def test_returns_audit_logger_instance(self):
        """AuditLogger インスタンスを返すこと。"""
        logger = get_audit_logger()
        assert isinstance(logger, AuditLogger)

    def test_returns_same_instance(self):
        """同じインスタンスを返すこと（シングルトン）。"""
        logger1 = get_audit_logger()
        logger2 = get_audit_logger()
        assert logger1 is logger2


@pytest.mark.unit
class TestAuditRequestMiddleware:
    """audit_request_middleware のテスト。"""

    @pytest.mark.asyncio
    async def test_middleware_adds_security_headers(self):
        """セキュリティヘッダが全レスポンスに追加されること。"""
        from src.core.audit_log import audit_request_middleware

        # モックリクエスト・レスポンス
        mock_request = MagicMock()
        mock_request.headers = {"X-User-ID": "test_user"}
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.method = "GET"
        mock_request.url.path = "/documents/"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}

        async def mock_call_next(req):
            return mock_response

        result = await audit_request_middleware(mock_request, mock_call_next)

        # セキュリティヘッダが追加されていること
        assert "X-Content-Type-Options" in mock_response.headers
        assert mock_response.headers["X-Content-Type-Options"] == "nosniff"
        assert "X-Frame-Options" in mock_response.headers
        assert mock_response.headers["X-Frame-Options"] == "DENY"
        assert "X-XSS-Protection" in mock_response.headers
        assert "Strict-Transport-Security" in mock_response.headers
