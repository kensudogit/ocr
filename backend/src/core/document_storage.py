"""書類原本ファイルの取得・DB 永続化ヘルパー。

Railway の ephemeral FS 対策として file_content (base64 TEXT) を優先し、
未保存の場合は uploads / 電子帳簿原本ディレクトリから読み込んで backfill する。
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Document

logger = logging.getLogger(__name__)


def originals_filepath(doc_id: uuid.UUID, doc: Document) -> Path:
    """電子帳簿保存法の原本保存パスを返す。"""
    suffix = ""
    if doc.file_path:
        suffix = Path(doc.file_path).suffix
    if not suffix and doc.original_filename:
        suffix = Path(doc.original_filename).suffix
    if not suffix:
        mime = doc.mime_type or ""
        suffix = ".pdf" if "pdf" in mime else ".png"
    return Path(settings.originals_dir) / "originals" / f"{doc_id}{suffix}"


async def backfill_file_content(doc: Document, raw: bytes, db: AsyncSession) -> None:
    """file_content が空のとき base64 テキストとして DB に保存する。"""
    if doc.file_content:
        return
    try:
        doc.file_content = base64.b64encode(raw).decode("ascii")
        await db.flush()
        logger.info("file_content を backfill: doc_id=%s size=%d", doc.id, len(raw))
    except Exception as exc:
        logger.warning("file_content backfill 失敗 doc_id=%s: %s", doc.id, exc)


async def load_document_bytes(
    doc: Document,
    db: AsyncSession | None = None,
    *,
    backfill: bool = True,
) -> bytes | None:
    """書類バイナリを取得する。

    優先順位:
      1. DB file_content (base64)
      2. uploads ディレクトリ (file_path)
      3. 電子帳簿原本ディレクトリ (originals/)
    """
    if doc.file_content:
        try:
            return base64.b64decode(doc.file_content)
        except Exception as exc:
            logger.warning("base64 decode 失敗 doc_id=%s: %s", doc.id, exc)

    if doc.file_path:
        fp = Path(doc.file_path)
        if fp.exists():
            raw = fp.read_bytes()
            if backfill and db is not None:
                await backfill_file_content(doc, raw, db)
            return raw

    orig = originals_filepath(doc.id, doc)
    if orig.exists():
        raw = orig.read_bytes()
        if backfill and db is not None:
            await backfill_file_content(doc, raw, db)
        return raw

    return None


def document_has_file(doc: Document) -> bool:
    """原本ファイルが取得可能かどうか（同期・一覧用の簡易チェック）。"""
    if doc.file_content:
        return True
    if doc.file_path and Path(doc.file_path).exists():
        return True
    return originals_filepath(doc.id, doc).exists()
