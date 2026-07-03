"""pytest 共通フィクスチャ・設定。

全テストモジュールから自動読み込みされる。
- テスト用 DB（SQLite インメモリ）
- FastAPI テストクライアント
- サンプル画像・テキスト生成ユーティリティ
"""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Generator
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

# テスト環境変数を最初に設定（importより前）
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("AI_DEPLOYMENT_MODE", "cloud")
os.environ.setdefault("UPLOAD_DIR", "/tmp/ocr_test_uploads")
os.environ.setdefault("EXPORT_DIR", "/tmp/ocr_test_exports")
os.environ.setdefault("ORIGINALS_DIR", "/tmp/ocr_test_originals")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")


# ── サンプルテキスト ──────────────────────────────────────────────────

SAMPLE_RECEIPT_TEXT = """
セブン-イレブン 渋谷店
2024年3月15日 14:32

コーヒー              220円
サンドイッチ           350円
  8%対象              350円

小計                  570円
消費税 (10%)           22円
消費税 (8%)            28円
合計                  620円

Tポイント利用           0P
お支払い               620円

登録番号 T1234567890137
レシートNO: 00012345
"""

SAMPLE_INVOICE_TEXT = """
請求書

株式会社サンプル御中

請求日: 令和6年3月31日
請求書番号: INV-2024-0315

品目             数量    単価      金額
システム開発費      1    500,000   500,000円
保守費用           1    100,000   100,000円

小計                           600,000円
消費税 (10%)                    60,000円
合計                           660,000円

振込先: ○○銀行 △△支店
普通口座: 1234567

適格請求書発行事業者番号
T9876543210987

支払期日: 令和6年4月30日
"""

SAMPLE_HANDWRITTEN_TEXT = """
領収書

上様

¥ 3,500-

但し 飲食代として

令和6年3月20日

山田商店
収入印紙
"""

SAMPLE_CARD_STATEMENT_TEXT = """
カード利用明細

カード番号: **** **** **** 1234
利用月: 2024年3月

利用日    加盟店名              金額
3/1    セブンイレブン          550円
3/5    東京電力               8,500円
3/10   Amazon.co.jp          3,200円
3/15   新宿レストラン         5,600円

今月ご利用金額合計       17,850円
お引落日: 4/27
"""


# ── サンプル画像生成 ──────────────────────────────────────────────────

def create_sample_image(
    width: int = 400,
    height: int = 600,
    text: str = "Sample Receipt",
    dpi: int = 200,
) -> bytes:
    """テスト用の簡易サンプル画像を生成する（Pillow を使用）。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (width, height), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), text, fill=(0, 0, 0))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", dpi=(dpi, dpi))
        return buf.getvalue()
    except Exception:
        # Pillow が使えない環境では最小限の JPEG バイト列を返す
        return (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
            b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
            b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=8"
            b"\x83\x82\x9d(`')\xff\xd9"
        )


# ── pytest フィクスチャ ──────────────────────────────────────────────

@pytest.fixture(scope="session")
def sample_receipt_text() -> str:
    return SAMPLE_RECEIPT_TEXT


@pytest.fixture(scope="session")
def sample_invoice_text() -> str:
    return SAMPLE_INVOICE_TEXT


@pytest.fixture(scope="session")
def sample_handwritten_text() -> str:
    return SAMPLE_HANDWRITTEN_TEXT


@pytest.fixture(scope="session")
def sample_card_text() -> str:
    return SAMPLE_CARD_STATEMENT_TEXT


@pytest.fixture(scope="session")
def sample_image_bytes() -> bytes:
    return create_sample_image(dpi=200)


@pytest.fixture(scope="session")
def low_dpi_image_bytes() -> bytes:
    """解像度不足のテスト用画像（150dpi）。"""
    return create_sample_image(dpi=150)


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """テスト用一時ディレクトリ。"""
    (tmp_path / "uploads").mkdir()
    (tmp_path / "exports").mkdir()
    (tmp_path / "originals").mkdir()
    return tmp_path


@pytest.fixture
def valid_invoice_number() -> str:
    """検証済みの有効なインボイス番号（国税庁の実在法人番号から生成）。"""
    # T + 法人番号 (チェックデジット: 7)
    # 例: 7000012050002 (法人番号 チェックデジット 7)
    return "T7000012050002"


@pytest.fixture
def invalid_invoice_number() -> str:
    """チェックデジット不正のインボイス番号。"""
    return "T1234567890123"
