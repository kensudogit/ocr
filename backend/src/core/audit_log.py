"""操作ログ・アクセス監査ログモジュール。

対応要件:
  - アクセスログ: 誰が・いつ・何を操作したか
  - 変更履歴: 仕訳データの修正前後を記録
  - セキュリティ監査: 認証失敗・不正アクセス試行の記録
  - 電子帳簿保存法: 入力者・確認者の記録

ログ形式:
  - DB テーブル（audit_logs）に構造化データとして保存
  - 重要ログは同時にファイルにも出力（DB 障害時のバックアップ）

FastAPI ミドルウェアとして登録:
  app.middleware("http")(audit_middleware)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── 監査ログのイベント種別 ──────────────────────────────────────────────
class AuditEventType:
    # 認証
    LOGIN           = "auth.login"
    LOGOUT          = "auth.logout"
    LOGIN_FAILED    = "auth.login_failed"

    # 書類操作
    DOC_UPLOAD      = "document.upload"
    DOC_VIEW        = "document.view"
    DOC_APPROVE     = "document.approve"
    DOC_REJECT      = "document.reject"
    DOC_EDIT        = "document.edit"
    DOC_DELETE      = "document.delete"
    DOC_EXPORT      = "document.export"

    # 仕訳操作
    JOURNAL_CREATE  = "journal.create"
    JOURNAL_EDIT    = "journal.edit"
    JOURNAL_APPROVE = "journal.approve"

    # 管理操作
    CLIENT_CREATE   = "client.create"
    CLIENT_EDIT     = "client.edit"
    SETTINGS_CHANGE = "settings.change"

    # システム
    AI_REQUEST      = "ai.request"           # AI へのリクエスト
    EXPORT_CSV      = "export.csv"
    EXPORT_API      = "export.api_call"


class AuditLogger:
    """構造化監査ログを記録するクラス。

    使い方:
        audit = AuditLogger()
        await audit.log(
            event_type=AuditEventType.DOC_APPROVE,
            user_id="staff_01",
            resource_id=str(doc_id),
            resource_type="document",
            detail={"before": {...}, "after": {...}},
            db=db,
        )
    """

    def __init__(self) -> None:
        self._file_logger = logging.getLogger("audit")

    async def log(
        self,
        event_type: str,
        user_id: str | None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        detail: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        db: AsyncSession | None = None,
        status: str = "success",
    ) -> None:
        """監査ログを記録する。

        Args:
            event_type:    イベント種別（AuditEventType の定数）
            user_id:       操作ユーザー ID
            resource_type: 操作対象リソース種別（"document", "client" 等）
            resource_id:   操作対象リソース ID（UUID）
            detail:        追加情報（変更前後の値等）
            ip_address:    クライアント IP アドレス
            user_agent:    User-Agent ヘッダ
            db:            DB セッション（DB 保存を行う場合）
            status:        "success" | "failure" | "warning"
        """
        log_entry = {
            "id":            str(uuid.uuid4()),
            "timestamp":     datetime.utcnow().isoformat(),
            "event_type":    event_type,
            "user_id":       user_id or "anonymous",
            "resource_type": resource_type,
            "resource_id":   resource_id,
            "status":        status,
            "ip_address":    ip_address,
            "detail":        detail or {},
        }

        # ファイルログ（JSON 形式）
        self._file_logger.info(json.dumps(log_entry, ensure_ascii=False))

        # DB 保存
        if db:
            try:
                await self._save_to_db(log_entry, db)
            except Exception as exc:
                logger.error("監査ログ DB 保存エラー: %s", exc)

    async def log_data_change(
        self,
        event_type: str,
        user_id: str | None,
        resource_type: str,
        resource_id: str,
        before: dict,
        after: dict,
        db: AsyncSession | None = None,
        ip_address: str | None = None,
    ) -> None:
        """データ変更の前後を記録する（変更履歴）。"""
        # 変更されたフィールドのみ抽出
        changes = {
            k: {"before": before.get(k), "after": after.get(k)}
            for k in set(list(before.keys()) + list(after.keys()))
            if before.get(k) != after.get(k)
        }
        await self.log(
            event_type=event_type,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            detail={"changes": changes},
            ip_address=ip_address,
            db=db,
        )

    @staticmethod
    async def _save_to_db(entry: dict, db: AsyncSession) -> None:
        """監査ログを DB に保存する。"""
        from src.db.models import AuditLog  # 循環import回避のため遅延インポート
        log = AuditLog(
            id=uuid.UUID(entry["id"]),
            event_type=entry["event_type"],
            user_id=entry["user_id"],
            resource_type=entry.get("resource_type"),
            resource_id=entry.get("resource_id"),
            status=entry.get("status", "success"),
            ip_address=entry.get("ip_address"),
            detail=entry.get("detail"),
        )
        db.add(log)
        await db.flush()


# ── FastAPI ミドルウェア ────────────────────────────────────────────────

async def audit_request_middleware(request: Request, call_next) -> Response:
    """全 HTTP リクエストを監査ログに記録するミドルウェア。

    app.middleware("http") として登録する。
    """
    start_time = time.perf_counter()

    # レスポンスを取得
    response: Response = await call_next(request)

    elapsed_ms = int((time.perf_counter() - start_time) * 1000)

    # ユーザー ID（将来的には JWT から取得）
    user_id = request.headers.get("X-User-ID", "anonymous")
    ip = request.client.host if request.client else "unknown"

    # ログレベルを HTTP ステータスで切り替え
    level = logging.WARNING if response.status_code >= 400 else logging.INFO
    logger.log(
        level,
        "%s %s %d %dms user=%s ip=%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        user_id,
        ip,
    )

    # セキュリティヘッダを追加
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    return response


# シングルトン
_audit_logger = AuditLogger()


def get_audit_logger() -> AuditLogger:
    return _audit_logger
