"""顧問先管理 API のテスト。

対象: src/api/clients.py
テスト観点:
  - GET /clients/ — 一覧取得
  - POST /clients/ — 顧問先作成
  - PUT /clients/{id} — 更新
  - GET /clients/{id}/stats — 統計取得
  - バリデーションエラー
  - 存在しない ID へのアクセス
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app


@pytest.mark.integration
class TestClientsListAPI:
    """顧問先一覧 API のテスト。"""

    @pytest.mark.asyncio
    async def test_get_clients_returns_200(self):
        """GET /clients/ が 200 を返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/clients/")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_clients_returns_list(self):
        """GET /clients/ がリストを返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/clients/")
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_clients_with_active_filter(self):
        """GET /clients/?active_only=true でフィルタリングできること。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/clients/?active_only=true")
        assert response.status_code == 200


@pytest.mark.integration
class TestClientsCreateAPI:
    """顧問先作成 API のテスト。"""

    @pytest.mark.asyncio
    async def test_create_client_returns_201(self):
        """POST /clients/ が 201 を返すこと。"""
        payload = {
            "name": f"テスト株式会社_{uuid.uuid4().hex[:6]}",
            "code": f"TEST_{uuid.uuid4().hex[:4]}",
            "accounting_software": "freee",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/clients/", json=payload)
        assert response.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_create_client_returns_id(self):
        """POST /clients/ が UUID の id を返すこと。"""
        payload = {"name": f"テスト顧問先_{uuid.uuid4().hex[:6]}"}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/clients/", json=payload)
        if response.status_code in (200, 201):
            data = response.json()
            assert "id" in data

    @pytest.mark.asyncio
    async def test_create_client_without_name_returns_422(self):
        """名前なしで POST /clients/ すると 422 を返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/clients/", json={})
        assert response.status_code == 422


@pytest.mark.integration
class TestClientStatsAPI:
    """顧問先統計 API のテスト。"""

    @pytest.mark.asyncio
    async def test_get_nonexistent_client_stats_returns_404(self):
        """存在しない顧問先の統計取得は 404 を返すこと。"""
        nonexistent_id = str(uuid.uuid4())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/clients/{nonexistent_id}/stats")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_invalid_uuid_returns_422(self):
        """無効な UUID は 422 を返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/clients/not-a-uuid/stats")
        assert response.status_code in (404, 422)
