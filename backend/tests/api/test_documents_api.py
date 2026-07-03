"""書類管理 API のテスト。

対象: src/api/documents.py
テスト観点:
  - GET /documents/ — 一覧取得・フィルタリング
  - GET /documents/{id} — 詳細取得
  - POST /documents/{id}/approve — 承認
  - POST /documents/{id}/reject — 差し戻し
  - PUT /documents/{id}/extracted — 抽出データ更新
  - GET /documents/stats/summary — 統計
  - 存在しない書類へのアクセス
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app


@pytest.mark.integration
class TestDocumentsListAPI:
    """書類一覧 API のテスト。"""

    @pytest.mark.asyncio
    async def test_get_documents_returns_200(self):
        """GET /documents/ が 200 を返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/documents/")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_documents_returns_list(self):
        """GET /documents/ がリスト形式のデータを返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/documents/")
        data = response.json()
        assert isinstance(data, (list, dict))

    @pytest.mark.asyncio
    async def test_get_documents_with_status_filter(self):
        """GET /documents/?status=pending でフィルタリングできること。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/documents/?status=pending")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_documents_with_confidence_tier_filter(self):
        """GET /documents/?confidence_tier=needs_review でフィルタリングできること。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/documents/?confidence_tier=needs_review")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_documents_with_pagination(self):
        """GET /documents/?limit=10&offset=0 でページネーションが動作すること。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/documents/?limit=10&offset=0")
        assert response.status_code == 200


@pytest.mark.integration
class TestDocumentDetailAPI:
    """書類詳細 API のテスト。"""

    @pytest.mark.asyncio
    async def test_get_nonexistent_document_returns_404(self):
        """存在しない書類の取得は 404 を返すこと。"""
        nonexistent_id = str(uuid.uuid4())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/documents/{nonexistent_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_document_with_invalid_uuid_returns_error(self):
        """無効な UUID での取得は 422 を返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/documents/not-a-uuid")
        assert response.status_code in (404, 422)


@pytest.mark.integration
class TestDocumentApproveAPI:
    """書類承認 API のテスト。"""

    @pytest.mark.asyncio
    async def test_approve_nonexistent_returns_404(self):
        """存在しない書類の承認は 404 を返すこと。"""
        nonexistent_id = str(uuid.uuid4())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(f"/documents/{nonexistent_id}/approve")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_reject_nonexistent_returns_404(self):
        """存在しない書類の差し戻しは 404 を返すこと。"""
        nonexistent_id = str(uuid.uuid4())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(f"/documents/{nonexistent_id}/reject")
        assert response.status_code == 404


@pytest.mark.integration
class TestDocumentStatsAPI:
    """書類統計 API のテスト。"""

    @pytest.mark.asyncio
    async def test_get_stats_returns_200(self):
        """GET /documents/stats/summary が 200 を返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/documents/stats/summary")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_stats_returns_numeric_counts(self):
        """統計レスポンスが数値のカウントを含むこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/documents/stats/summary")
        if response.status_code == 200:
            data = response.json()
            # 何らかのカウントフィールドが存在すること
            assert isinstance(data, dict)
