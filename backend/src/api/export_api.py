"""エクスポート API エンドポイント。"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.config import settings
from src.core.exporter import export
from src.db.database import get_db
from src.db.models import DocStatus, Document, ExportLog, ExtractedData
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/export", tags=["export"])


@router.post("", summary="承認済み書類をエクスポート（末尾スラッシュなし）")
@router.post("/", summary="承認済み書類をエクスポート")
async def export_documents(
    fmt: str = Query("freee", description="エクスポート形式: freee / money_forward / yayoi / generic_csv"),
    doc_ids: list[uuid.UUID] | None = Query(None, description="エクスポート対象書類IDリスト（省略時は全承認済み）"),
    exported_by: str = Query("staff"),
    db: AsyncSession = Depends(get_db),
):
    """承認済み書類を会計ソフト連携 CSV でエクスポートする。

    freee / マネーフォワード / 弥生会計 / 汎用CSV に対応。
    """
    stmt = (
        select(Document)
        .options(selectinload(Document.extracted))
        .where(Document.status == DocStatus.APPROVED)
    )
    if doc_ids:
        stmt = stmt.where(Document.id.in_(doc_ids))

    docs = (await db.execute(stmt)).scalars().all()

    if not docs:
        raise HTTPException(status_code=404, detail="エクスポート対象の承認済み書類がありません")

    pairs = [(doc, doc.extracted) for doc in docs]

    try:
        csv_bytes, filename, content_type = export(pairs, fmt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # エクスポートログを記録
    for doc in docs:
        db.add(ExportLog(
            document_id=doc.id,
            export_format=fmt,
            exported_by=exported_by,
            row_count=len(docs),
        ))
        doc.status = DocStatus.EXPORTED

    await db.flush()

    return Response(
        content=csv_bytes,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/formats", summary="対応エクスポートフォーマット一覧")
async def list_formats():
    """対応している会計ソフト連携フォーマットの一覧を返す。"""
    return {
        "formats": [
            {
                "id": "freee",
                "name": "freee会計",
                "description": "freee会計 仕訳インポートCSV（UTF-8 BOM付き）",
                "encoding": "UTF-8 BOM",
            },
            {
                "id": "money_forward",
                "name": "マネーフォワード クラウド会計",
                "description": "マネーフォワード 仕訳帳CSVインポート（UTF-8 BOM付き）",
                "encoding": "UTF-8 BOM",
            },
            {
                "id": "yayoi",
                "name": "弥生会計",
                "description": "弥生会計 仕訳日記帳CSVインポート（Shift-JIS）",
                "encoding": "Shift-JIS",
            },
            {
                "id": "generic_csv",
                "name": "汎用CSV",
                "description": "全フィールドを含む汎用CSVファイル（UTF-8 BOM付き）",
                "encoding": "UTF-8 BOM",
            },
        ]
    }
