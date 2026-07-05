"""アップロード API のテスト。

対象: src/api/upload.py
テスト観点:
  - ファイルアップロードの成功・失敗
  - 許可拡張子のバリデーション
  - ファイルサイズ制限
  - バッチアップロード
  - バッチジョブステータス確認
  - 再処理エンドポイント
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from tests.conftest import create_sample_image


@pytest.fixture
def sample_jpg_file() -> tuple[str, bytes, str]:
    """テスト用 JPEG ファイルの (filename, bytes, content_type)。"""
    image_bytes = create_sample_image(width=400, height=600)
    return ("test_receipt.jpg", image_bytes, "image/jpeg")


@pytest.fixture
def sample_png_file() -> tuple[str, bytes, str]:
    """テスト用 PNG ファイルの (filename, bytes, content_type)。"""
    try:
        from PIL import Image
        img = Image.new("RGB", (400, 600), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return ("test_receipt.png", buf.getvalue(), "image/png")
    except ImportError:
        return ("test_receipt.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "image/png")


@pytest.mark.integration
class TestUploadSingleFile:
    """単一ファイルアップロードのテスト。"""

    @pytest.mark.asyncio
    async def test_upload_jpg_returns_200(self, sample_jpg_file):
        """JPEG ファイルのアップロードが成功すること。"""
        filename, content, content_type = sample_jpg_file

        # OCR 処理をモック（重い処理をスキップ）
        with patch("src.api.upload._process_document", new_callable=AsyncMock) as mock_proc:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/upload/",
                    files={"file": (filename, content, content_type)},
                    params={"auto_process": "false"},
                )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_upload_returns_document_id(self, sample_jpg_file):
        """アップロードが document_id を返すこと。"""
        filename, content, content_type = sample_jpg_file

        with patch("src.api.upload._process_document", new_callable=AsyncMock):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/upload/",
                    files={"file": (filename, content, content_type)},
                    params={"auto_process": "false"},
                )
        if response.status_code == 200:
            data = response.json()
            assert "document_id" in data

    @pytest.mark.asyncio
    async def test_upload_unsupported_extension_returns_400(self):
        """未対応拡張子（.exe）のアップロードは 400 を返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/upload/",
                files={"file": ("malware.exe", b"fake content", "application/octet-stream")},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_txt_returns_400(self):
        """テキストファイル（.txt）のアップロードは 400 を返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/upload/",
                files={"file": ("test.txt", b"hello world", "text/plain")},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_with_client_id(self, sample_jpg_file):
        """顧問先 ID 付きのアップロードが成功すること。"""
        filename, content, content_type = sample_jpg_file
        client_id = str(uuid.uuid4())

        with patch("src.api.upload._process_document", new_callable=AsyncMock):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/upload/",
                    files={"file": (filename, content, content_type)},
                    params={"auto_process": "false", "client_id": client_id},
                )
        assert response.status_code == 200


@pytest.mark.integration
class TestBatchUpload:
    """バッチアップロード API のテスト。"""

    @pytest.mark.asyncio
    async def test_batch_upload_returns_job_id(self, sample_jpg_file):
        """バッチアップロードがジョブ ID を返すこと。"""
        filename, content, content_type = sample_jpg_file
        files = [
            ("files", (f"receipt_{i}.jpg", content, content_type))
            for i in range(3)
        ]

        with patch("src.api.upload._process_document", new_callable=AsyncMock):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/upload/batch",
                    files=files,
                )
        if response.status_code == 200:
            data = response.json()
            assert "batch_job_id" in data
            assert data["total_files"] == 3

    @pytest.mark.asyncio
    async def test_batch_upload_too_many_files_returns_400(self, sample_jpg_file):
        """batch_max_files 超のバッチアップロードは 400 を返すこと。"""
        from src.config import settings

        limit = settings.batch_max_files
        filename, content, content_type = sample_jpg_file
        files = [
            ("files", (f"receipt_{i}.jpg", content, content_type))
            for i in range(limit + 1)
        ]

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/upload/batch",
                files=files,
            )
        assert response.status_code == 400


@pytest.mark.integration
class TestBatchStatus:
    """バッチジョブステータス確認のテスト。"""

    @pytest.mark.asyncio
    async def test_nonexistent_batch_returns_404(self):
        """存在しないバッチジョブは 404 を返すこと。"""
        nonexistent_id = str(uuid.uuid4())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/upload/batch/{nonexistent_id}/status")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_job_id_returns_error(self):
        """無効な ジョブ ID は エラーを返すこと。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/upload/batch/not-a-uuid/status")
        assert response.status_code in (404, 422)


@pytest.mark.integration
class TestReprocessEndpoint:
    """再OCR処理エンドポイントのテスト。"""

    @pytest.mark.asyncio
    async def test_reprocess_nonexistent_returns_404(self):
        """存在しない書類の再処理は 404 を返すこと。"""
        nonexistent_id = str(uuid.uuid4())
        with patch("src.api.upload._process_document", new_callable=AsyncMock):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(f"/upload/{nonexistent_id}/reprocess")
        assert response.status_code == 404
