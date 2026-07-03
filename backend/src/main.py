"""税理士事務所向け OCR システム — FastAPI アプリケーション。

エンドポイント一覧:
  POST   /upload/              1ファイルアップロード + 即時OCR
  POST   /upload/batch         複数ファイル一括アップロード
  GET    /upload/batch/{id}/status  バッチ進捗確認
  POST   /upload/{id}/reprocess     再OCR処理

  GET    /documents/           書類一覧（フィルタ・ページネーション）
  GET    /documents/{id}       書類詳細
  PUT    /documents/{id}/extracted  抽出データ手動修正
  POST   /documents/{id}/approve   承認
  POST   /documents/{id}/reject    差し戻し
  DELETE /documents/{id}       削除
  GET    /documents/stats/summary  統計サマリー

  POST   /export/              会計ソフト向けCSVエクスポート
  GET    /export/formats       対応フォーマット一覧

  GET    /health               ヘルスチェック
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.clients import router as client_router
from src.api.documents import router as doc_router
from src.api.export_api import router as export_router
from src.api.test_report import router as test_report_router
from src.api.upload import router as upload_router
from src.config import settings
from src.core.audit_log import audit_request_middleware
from src.db.database import create_tables

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── FastAPI アプリ ────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="""
## 税理士事務所向け OCR 自動仕訳システム

対象書類:
- 感熱紙レシート（コンビニ・スーパー等）
- 手書き領収書
- 請求書（PDF・画像）
- クレジットカード明細

### 主な機能
1. **自動OCR処理** - PaddleOCR + Google Vision API (フォールバック)
2. **データ抽出** - 日付・金額・消費税・店舗名・適格請求書番号
3. **手動確認・修正** - Web UI で抽出結果を確認・編集
4. **会計ソフト連携** - freee / マネーフォワード / 弥生会計 / 汎用CSV エクスポート
5. **バッチ処理** - 月500枚以上の一括処理に対応
""",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ─────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 監査ログ・セキュリティヘッダミドルウェア ────────────────────────
app.middleware("http")(audit_request_middleware)

# ── ルーター登録 ──────────────────────────────────────────────────────
app.include_router(upload_router)
app.include_router(doc_router)
app.include_router(export_router)
app.include_router(client_router)
app.include_router(test_report_router)

# ── 静的ファイル（アップロード済み画像プレビュー用） ─────────────────
import os as _os
if _os.path.isdir(settings.upload_dir):
    app.mount("/files", StaticFiles(directory=settings.upload_dir), name="uploads")


# ── ライフサイクル ────────────────────────────────────────────────────
@app.on_event("startup")
async def startup() -> None:
    """アプリ起動時にDBテーブルを作成する。DB未接続でも起動継続する。"""
    try:
        logger.info("データベーステーブルを初期化中...")
        await create_tables()
        logger.info("DB初期化完了")
    except Exception as exc:
        logger.warning("DB初期化スキップ（接続不可）: %s", exc)
    logger.info("起動完了 — %s v%s", settings.app_name, settings.app_version)


# ── ルート ───────────────────────────────────────────────────────────
@app.get("/", tags=["system"])
async def root():
    """ルートエンドポイント — API 情報を返す。"""
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }


# ── ヘルスチェック ────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health():
    """ヘルスチェックエンドポイント。"""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "ocr_engine": settings.ocr_engine,
        "ai_deployment_mode": settings.ai_deployment_mode,
        "pii_masking": settings.ai_deployment_mode == "hybrid",
    }
