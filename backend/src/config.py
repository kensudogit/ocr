"""アプリケーション設定モジュール。

.env ファイルまたは環境変数から設定を読み込む。
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── アプリ基本 ────────────────────────────────────────────
    app_name: str = "税理士OCRシステム"
    app_version: str = "1.0.0"
    debug: bool = False

    # ── データベース ──────────────────────────────────────────
    # Default: SQLite (works without external DB, good for PoC / Railway)
    # Set DATABASE_URL env var to use PostgreSQL:
    #   postgresql+psycopg://user:pass@host:5432/db
    database_url: str = "sqlite+aiosqlite:///./ocr.db"

    @property
    def database_url_normalized(self) -> str:
        """Normalize DATABASE_URL for the correct async driver (asyncpg).

        - postgres:// / postgresql:// → postgresql+asyncpg://
        - Railway *internal* URLs (*.railway.internal) do NOT support SSL;
          Railway *external* URLs (*.railway.app / *.up.railway.app) require SSL.
        """
        url = self.database_url
        if url.startswith("sqlite"):
            return url
        # Normalise scheme to postgresql+asyncpg
        for prefix in ("postgres://", "postgresql://", "postgresql+psycopg://",
                       "postgresql+psycopg2://"):
            if url.startswith(prefix):
                url = "postgresql+asyncpg://" + url[len(prefix):]
                break
        # Only append sslmode for external (non-internal) connections.
        # railway.internal hosts are reached over Railway's private network
        # and do NOT support SSL; adding sslmode=require would break them.
        is_internal = ".railway.internal" in url or "localhost" in url or "127.0.0.1" in url
        if not is_internal and "ssl" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}ssl=true"
        return url

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.database_url

    # ── ファイル保存 ──────────────────────────────────────────
    upload_dir: str = str(Path(__file__).parent.parent / "uploads")
    export_dir: str = str(Path(__file__).parent.parent / "exports")
    max_upload_size_mb: int = 50  # 1ファイル最大 50MB
    allowed_extensions: list[str] = [".jpg", ".jpeg", ".png", ".pdf", ".tiff", ".tif", ".bmp", ".webp"]

    # ── OCR エンジン ──────────────────────────────────────────
    ocr_engine: str = "paddle"  # "paddle" | "google" | "auto"
    google_vision_api_key: str = ""  # Google Cloud Vision API キー
    google_vision_project_id: str = ""
    ocr_language: str = "ja"

    # ── 画像前処理 ────────────────────────────────────────────
    # 感熱紙レシート用: コントラスト強調を有効化
    enhance_thermal_paper: bool = True
    # 自動回転補正
    auto_rotate: bool = True
    # ノイズ除去強度 (0=無効, 1=弱, 2=中, 3=強)
    denoise_level: int = 2

    # ── バックグラウンドタスク ──────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_enabled: bool = False  # False: 同期処理, True: Celery非同期

    # ── VLM（Vision Language Model） ─────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # ── freee 公式 API ────────────────────────────────────────────
    freee_client_id: str = ""
    freee_client_secret: str = ""
    freee_access_token: str = ""
    freee_company_id: str = ""

    # ── AI デプロイメントモード ────────────────────────────────────
    # "cloud"  : OpenAI / Gemini（ZDR設定、データ国内外）
    # "hybrid" : ローカルPIIマスク → クラウドAI（推奨バランス）
    # "bedrock": AWS Bedrock（東京/大阪リージョン、データ国内）
    # "vertex" : Google Vertex AI（日本リージョン、データ国内）
    # "onprem" : 完全ローカル（PaddleOCR + Ollama）
    ai_deployment_mode: str = "cloud"

    # ── AWS Bedrock（オンプレ・国内固定構成） ───────────────────────
    aws_region: str = "ap-northeast-1"        # 東京リージョン（大阪: ap-northeast-3）
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    # ── Google Vertex AI（国内固定構成） ──────────────────────────
    gcp_project_id: str = ""
    vertex_location: str = "asia-northeast1"  # 東京リージョン（大阪: asia-northeast2）

    # ── Ollama（完全オンプレ構成） ────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2-vision"

    # ── PII マスク設定 ────────────────────────────────────────────
    # ハイブリッド構成で有効にする個人情報の種別
    pii_mask_bank_accounts: bool = True   # 銀行口座番号をマスク
    pii_mask_my_number: bool = True       # マイナンバーをマスク
    pii_mask_card_numbers: bool = True    # クレジットカード番号をマスク
    pii_mask_phone_numbers: bool = False  # 電話番号はデフォルト OFF

    # ── 電子帳簿保存法対応 ────────────────────────────────────────
    scan_min_dpi: int = 200               # スキャン最低解像度
    originals_dir: str = str(Path(__file__).parent.parent / "originals")
    timestamp_deadline_days: int = 2      # タイムスタンプ付与期限（営業日）

    # ── 暗号化 ────────────────────────────────────────────────────
    # Django SECRET_KEY 相当。本番は強力なランダム値に変更してください
    secret_key: str = "change-me-in-production-use-strong-random-value"
    # ファイル暗号化（原本画像の保存時暗号化）
    encrypt_stored_files: bool = False    # True: AES-256 で暗号化

    # ── CORS ─────────────────────────────────────────────────
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# ── ディレクトリ作成 ───────────────────────────────────────────
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
Path(settings.export_dir).mkdir(parents=True, exist_ok=True)
Path(settings.originals_dir).mkdir(parents=True, exist_ok=True)
