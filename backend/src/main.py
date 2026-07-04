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
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# ── ロギング（設定より先に初期化） ────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── 設定（失敗しても最低限の設定でフォールバック） ─────────────────────
try:
    from src.config import settings
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True,
    )
    logger.info("src.config: loaded OK")
except Exception as _cfg_exc:
    logger.error("src.config: FAILED — %s\n%s", _cfg_exc, traceback.format_exc())
    # ミニマル設定フォールバック
    from types import SimpleNamespace
    settings = SimpleNamespace(  # type: ignore[assignment]
        app_name="税理士OCRシステム",
        app_version="1.0.0",
        debug=False,
        upload_dir="/api/uploads",
        allowed_origins=["*"],
        ocr_engine="none",
        ai_deployment_mode="cloud",
    )

# ── DB（失敗しても起動継続） ──────────────────────────────────────────
_create_tables_fn = None
try:
    from src.db.database import create_tables as _create_tables_fn  # type: ignore[assignment]
    logger.info("src.db.database: loaded OK")
except Exception as _db_exc:
    logger.error("src.db.database: FAILED — %s\n%s", _db_exc, traceback.format_exc())

async def create_tables() -> None:  # type: ignore[misc]
    if _create_tables_fn is not None:
        await _create_tables_fn()

# ── オプションルーター（import 失敗しても起動継続） ───────────────────
_import_errors: list[str] = []

def _try_import(label: str, import_fn):
    """ルーターを安全にインポートする。失敗してもアプリは起動する。"""
    try:
        return import_fn()
    except Exception as exc:  # noqa: BLE001
        msg = f"{label}: {type(exc).__name__}: {exc}"
        logger.error("ルーター読み込み失敗 — %s\n%s", msg, traceback.format_exc())
        _import_errors.append(msg)
        return None

upload_router    = _try_import("upload",      lambda: __import__("src.api.upload",      fromlist=["router"]).router)
doc_router       = _try_import("documents",   lambda: __import__("src.api.documents",   fromlist=["router"]).router)
export_router    = _try_import("export_api",  lambda: __import__("src.api.export_api",  fromlist=["router"]).router)
client_router    = _try_import("clients",     lambda: __import__("src.api.clients",     fromlist=["router"]).router)
test_report_router = _try_import("test_report", lambda: __import__("src.api.test_report", fromlist=["router"]).router)

audit_request_middleware = _try_import(
    "audit_log",
    lambda: __import__("src.core.audit_log", fromlist=["audit_request_middleware"]).audit_request_middleware,
)

# ── FastAPI アプリ ────────────────────────────────────────────────────
app = FastAPI(
    title=getattr(settings, "app_name", "税理士OCRシステム"),
    version=getattr(settings, "app_version", "1.0.0"),
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
    # redirect_slashes=True (default): FastAPI redirects /documents → /documents/ with 307.
    # The Next.js proxy uses redirect:"follow" so it follows the 307 internally and
    # returns 200 to the browser. Do NOT set redirect_slashes=False — that turns the
    # redirect into a 404 because routes are defined with trailing slashes.
)

# ── CORS ─────────────────────────────────────────────────────────────
# All browser→backend traffic goes through the Next.js server-side proxy,
# so the Origin is irrelevant. Allow "*" to avoid accidental CORS blocks.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # must be False when allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 監査ログミドルウェア（失敗しても起動継続） ───────────────────────
if audit_request_middleware is not None:
    app.middleware("http")(audit_request_middleware)

# ── ルーター登録（None のものはスキップ） ─────────────────────────────
for _router in [upload_router, doc_router, export_router, client_router, test_report_router]:
    if _router is not None:
        app.include_router(_router)

# ── 静的ファイル（アップロード済み画像プレビュー用） ─────────────────
from pathlib import Path as _Path
_Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=settings.upload_dir), name="uploads")


# ── ライフサイクル ────────────────────────────────────────────────────
@app.on_event("startup")
async def startup() -> None:
    """アプリ起動時にDBテーブルを作成する。DB未接続でも起動継続する。"""
    try:
        logger.info("データベーステーブルを初期化中...")
        await create_tables()
        # file_content カラムが存在しない旧テーブルへのマイグレーション
        await _migrate_add_file_content()
        logger.info("DB初期化完了")
    except Exception as exc:
        logger.warning("DB初期化スキップ（接続不可）: %s", exc)
    logger.info("起動完了 — %s v%s", settings.app_name, settings.app_version)


async def _migrate_add_file_content() -> None:
    """既存の documents テーブルに file_content (TEXT/base64) カラムを追加する（冪等）。

    前回デプロイで BYTEA として作成済みの場合は削除して TEXT で再作成する。
    データ損失は許容（BYTEA 版は表示できなかったため）。
    """
    from src.db.database import engine
    from sqlalchemy import text
    try:
        async with engine.begin() as conn:
            # 1. BYTEA で作成されていれば削除（前回デプロイの残骸）
            #    PostgreSQL 専用構文のため SQLite では例外を無視
            try:
                await conn.execute(text("""
                    DO $$BEGIN
                      IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                         WHERE table_name='documents'
                           AND column_name='file_content'
                           AND udt_name='bytea'
                      ) THEN
                        ALTER TABLE documents DROP COLUMN file_content;
                      END IF;
                    END$$
                """))
            except Exception:
                pass  # SQLite など非対応環境ではスキップ

            # 2. TEXT カラムとして追加（既に TEXT で存在する場合は重複エラーを無視）
            try:
                await conn.execute(text(
                    "ALTER TABLE documents ADD COLUMN file_content TEXT"
                ))
            except Exception:
                pass  # 既存の場合は無視
    except Exception as exc:
        logger.debug("file_content マイグレーション: %s", exc)


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
        "app": getattr(settings, "app_name", "税理士OCRシステム"),
        "version": getattr(settings, "app_version", "1.0.0"),
        "ocr_engine": getattr(settings, "ocr_engine", "none"),
        "ai_deployment_mode": getattr(settings, "ai_deployment_mode", "cloud"),
        "import_errors": _import_errors,  # [] if all modules loaded OK
    }
