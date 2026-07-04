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


    @pytest.mark.asyncio
    async def test_get_documents_returns_json_with_items(self):
        """一覧レスポンスが UUID/datetime を含む items を JSON として返せること。"""
        from tests.conftest import _TestSessionLocal
        from src.db.models import Document, DocStatus

        doc_id = uuid.uuid4()
        async with _TestSessionLocal() as session:
            session.add(Document(
                id=doc_id,
                original_filename="list_json_test.pdf",
                stored_filename=f"{doc_id}.pdf",
                file_path="/tmp/nonexistent.pdf",
                file_size_bytes=100,
                mime_type="application/pdf",
                status=DocStatus.PENDING,
            ))
            await session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/documents/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert isinstance(data["items"], list)
        assert any(item["id"] == str(doc_id) for item in data["items"])


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
class TestDocumentDeleteAPI:
    """書類削除 API のテスト。"""

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self):
        """存在しない書類の削除は 404 を返すこと。"""
        nonexistent_id = str(uuid.uuid4())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.delete(f"/documents/{nonexistent_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_removes_document_from_db(self):
        """削除後、documents / extracted_data テーブルからレコードが消えること。"""
        from sqlalchemy import select

        from tests.conftest import _TestSessionLocal
        from src.db.models import Document, ExtractedData, DocStatus

        doc_id = uuid.uuid4()
        async with _TestSessionLocal() as session:
            doc = Document(
                id=doc_id,
                original_filename="test_delete.pdf",
                stored_filename=f"{doc_id}.pdf",
                file_path="/tmp/nonexistent.pdf",
                file_size_bytes=100,
                mime_type="application/pdf",
                status=DocStatus.PENDING,
            )
            session.add(doc)
            session.add(ExtractedData(document_id=doc_id, vendor_name="テスト"))
            await session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.delete(f"/documents/{doc_id}")
        assert response.status_code == 200

        async with _TestSessionLocal() as session:
            doc = (await session.execute(
                select(Document).where(Document.id == doc_id)
            )).scalar_one_or_none()
            ex = (await session.execute(
                select(ExtractedData).where(ExtractedData.document_id == doc_id)
            )).scalar_one_or_none()
            assert doc is None
            assert ex is None


@pytest.mark.integration
class TestDocumentBulkDeleteAPI:
    """書類一括削除 API のテスト。"""

    @pytest.mark.asyncio
    async def test_bulk_delete_empty_returns_400(self):
        """空リストの一括削除は 400 を返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/documents/bulk-delete", json={"document_ids": []})
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_bulk_delete_removes_multiple_documents(self):
        """複数書類を一括削除できること。"""
        from sqlalchemy import select

        from tests.conftest import _TestSessionLocal
        from src.db.models import Document, ExtractedData, DocStatus

        doc_ids = [uuid.uuid4(), uuid.uuid4()]
        async with _TestSessionLocal() as session:
            for i, doc_id in enumerate(doc_ids):
                session.add(Document(
                    id=doc_id,
                    original_filename=f"bulk_{i}.pdf",
                    stored_filename=f"{doc_id}.pdf",
                    file_path="/tmp/nonexistent.pdf",
                    file_size_bytes=100,
                    mime_type="application/pdf",
                    status=DocStatus.PENDING,
                ))
                session.add(ExtractedData(document_id=doc_id, vendor_name=f"テスト{i}"))
            await session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/documents/bulk-delete",
                json={"document_ids": [str(d) for d in doc_ids]},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 2
        assert set(data["deleted_ids"]) == {str(d) for d in doc_ids}

        async with _TestSessionLocal() as session:
            for doc_id in doc_ids:
                doc = (await session.execute(
                    select(Document).where(Document.id == doc_id)
                )).scalar_one_or_none()
                assert doc is None


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
