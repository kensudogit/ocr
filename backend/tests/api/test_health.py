"""FastAPI アプリ・ヘルスチェックのテスト。

対象: src/main.py（アプリ起動・ヘルスチェックエンドポイント）
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app


@pytest.mark.integration
class TestHealthEndpoint:
    """ヘルスチェックエンドポイントのテスト。"""

    @pytest.mark.asyncio
    async def test_health_returns_200(self):
        """GET /health が 200 を返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_response_has_status_ok(self):
        """/health レスポンスに status='ok' が含まれること。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
        data = response.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_response_has_app_name(self):
        """/health レスポンスにアプリ名が含まれること。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
        data = response.json()
        assert "app" in data
        assert isinstance(data["app"], str)

    @pytest.mark.asyncio
    async def test_health_response_has_ai_deployment_mode(self):
        """/health レスポンスに ai_deployment_mode が含まれること。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
        data = response.json()
        assert "ai_deployment_mode" in data

    @pytest.mark.asyncio
    async def test_docs_endpoint_accessible(self):
        """GET /docs（Swagger UI）が 200 を返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/docs")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi_json_accessible(self):
        """GET /openapi.json が 200 を返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data


@pytest.mark.unit
class TestAppConfiguration:
    """アプリ設定のテスト。"""

    def test_app_has_title(self):
        """FastAPI アプリにタイトルが設定されていること。"""
        assert app.title is not None
        assert isinstance(app.title, str)
        assert len(app.title) > 0

    def test_app_has_version(self):
        """FastAPI アプリにバージョンが設定されていること。"""
        assert app.version is not None

    def test_routers_are_registered(self):
        """主要ルーターが登録されていること。"""
        route_paths = [getattr(route, "path", "") for route in app.routes]
        # 主要エンドポイントが存在すること
        assert any("/upload" in p for p in route_paths)
        assert any("/documents" in p for p in route_paths)
        assert any("/health" in p for p in route_paths)
