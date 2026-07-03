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
from fastapi.responses import HTMLResponse
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
@app.get("/", response_class=HTMLResponse, tags=["system"])
async def root():
    """サービス案内ページ。"""
    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{settings.app_name}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #f1f5f9;
    }}
    .container {{
      max-width: 720px;
      width: 90%;
      padding: 48px 40px;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 24px;
      backdrop-filter: blur(12px);
    }}
    .badge {{
      display: inline-block;
      background: #22c55e20;
      color: #4ade80;
      border: 1px solid #22c55e40;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      padding: 4px 12px;
      margin-bottom: 20px;
      letter-spacing: 0.05em;
    }}
    h1 {{
      font-size: 32px;
      font-weight: 700;
      line-height: 1.2;
      margin-bottom: 8px;
    }}
    .version {{
      color: #94a3b8;
      font-size: 14px;
      margin-bottom: 32px;
    }}
    .description {{
      color: #cbd5e1;
      font-size: 15px;
      line-height: 1.7;
      margin-bottom: 36px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 32px;
    }}
    @media (max-width: 500px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
    .card {{
      display: block;
      text-decoration: none;
      padding: 16px 20px;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 12px;
      transition: all 0.2s;
    }}
    .card:hover {{
      background: rgba(255,255,255,0.1);
      border-color: rgba(99,102,241,0.5);
      transform: translateY(-2px);
    }}
    .card-icon {{ font-size: 22px; margin-bottom: 8px; }}
    .card-title {{ font-size: 14px; font-weight: 600; color: #f1f5f9; }}
    .card-desc {{ font-size: 12px; color: #94a3b8; margin-top: 2px; }}
    .status-bar {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px 16px;
      background: rgba(34,197,94,0.1);
      border: 1px solid rgba(34,197,94,0.2);
      border-radius: 10px;
      font-size: 13px;
      color: #4ade80;
    }}
    .dot {{
      width: 8px; height: 8px;
      background: #22c55e;
      border-radius: 50%;
      animation: pulse 2s infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: 0.4; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="badge">✓ RUNNING</div>
    <h1>🧾 {settings.app_name}</h1>
    <div class="version">v{settings.app_version} &nbsp;·&nbsp; FastAPI バックエンド</div>
    <p class="description">
      税理士事務所向け AI-OCR 自動仕訳システム。<br>
      領収書・請求書の画像から仕訳データを自動生成し、
      freee / マネーフォワード / 弥生会計へエクスポートします。
    </p>
    <div class="grid">
      <a href="/docs" class="card">
        <div class="card-icon">📚</div>
        <div class="card-title">API ドキュメント</div>
        <div class="card-desc">Swagger UI でインタラクティブに試せます</div>
      </a>
      <a href="/redoc" class="card">
        <div class="card-icon">📖</div>
        <div class="card-title">ReDoc</div>
        <div class="card-desc">見やすい API リファレンス</div>
      </a>
      <a href="/health" class="card">
        <div class="card-icon">💚</div>
        <div class="card-title">ヘルスチェック</div>
        <div class="card-desc">サービス稼働状況の確認</div>
      </a>
      <a href="/upload/" class="card">
        <div class="card-icon">📤</div>
        <div class="card-title">アップロード API</div>
        <div class="card-desc">書類のアップロード・OCR 処理</div>
      </a>
    </div>
    <div class="status-bar">
      <div class="dot"></div>
      バックエンド API は正常稼働中です
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


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
