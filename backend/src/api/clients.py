"""顧問先管理 API エンドポイント。"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_db
from src.db.models import Client, Document, JournalHistory

router = APIRouter(prefix="/clients", tags=["clients"])


class ClientCreate(BaseModel):
    name: str
    code: str | None = None
    fiscal_year_end: int | None = None
    accounting_software: str | None = None


class ClientUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    fiscal_year_end: int | None = None
    accounting_software: str | None = None
    freee_company_id: str | None = None


@router.get("/", summary="顧問先一覧")
async def list_clients(db: AsyncSession = Depends(get_db)):
    clients = (await db.execute(select(Client).where(Client.is_active == True))).scalars().all()
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "code": c.code,
            "accounting_software": c.accounting_software,
            "fiscal_year_end": c.fiscal_year_end,
        }
        for c in clients
    ]


@router.post("/", summary="顧問先追加")
async def create_client(body: ClientCreate, db: AsyncSession = Depends(get_db)):
    c = Client(**body.model_dump(exclude_none=True))
    db.add(c)
    await db.flush()
    return {"id": str(c.id), "name": c.name, "message": "顧問先を追加しました"}


@router.put("/{client_id}", summary="顧問先更新")
async def update_client(client_id: uuid.UUID, body: ClientUpdate, db: AsyncSession = Depends(get_db)):
    c = (await db.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="顧問先が見つかりません")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    await db.flush()
    return {"message": "更新しました"}


@router.get("/{client_id}/stats", summary="顧問先の処理統計")
async def get_client_stats(client_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """顧問先ごとの処理統計を返す。"""
    from src.db.models import DocStatus
    total = (await db.execute(
        select(func.count(Document.id)).where(Document.client_id == client_id)
    )).scalar_one()
    auto = (await db.execute(
        select(func.count(Document.id)).where(
            Document.client_id == client_id,
            Document.confidence_tier == "auto_confirmed"
        )
    )).scalar_one()
    needs_review = (await db.execute(
        select(func.count(Document.id)).where(
            Document.client_id == client_id,
            Document.confidence_tier == "needs_review"
        )
    )).scalar_one()
    return {
        "client_id": str(client_id),
        "total_documents": total,
        "auto_confirmed": auto,
        "needs_review": needs_review,
        "manual_input": total - auto - needs_review,
        "auto_rate": round(auto / max(total, 1) * 100, 1),
    }


@router.get("/{client_id}/journal-history", summary="過去仕訳履歴")
async def get_journal_history(
    client_id: uuid.UUID,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """顧問先の過去仕訳履歴（ルールエンジン学習データ）を返す。"""
    history = (
        await db.execute(
            select(JournalHistory)
            .where(JournalHistory.client_id == client_id)
            .order_by(JournalHistory.use_count.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "vendor_name":   h.vendor_name,
            "account_title": h.account_title,
            "tax_category":  h.tax_category,
            "use_count":     h.use_count,
            "last_used_at":  h.last_used_at,
        }
        for h in history
    ]
