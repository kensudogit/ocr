"""画像前処理モジュール（PIL のみ版）。

OpenCV を使わず Pillow だけで実装することで、
Railway などの軽量 Linux 環境でも確実に動作する。

対応書類:
  - 感熱紙レシート: コントラスト強調
  - 手書き領収書: シャープニング
  - 請求書・カード明細: 解像度正規化
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

logger = logging.getLogger(__name__)


@dataclass
class PreprocessResult:
    """前処理結果。"""
    image: np.ndarray                          # 処理済み画像（NumPy配列）
    pil_image: Image.Image                     # PIL イメージ（OCRエンジン用）
    applied_steps: list[str] = field(default_factory=list)
    skew_angle: float = 0.0
    original_size: tuple[int, int] = (0, 0)   # (H, W)
    final_size: tuple[int, int] = (0, 0)       # (H, W)
    is_thermal_paper: bool = False
    confidence: float = 1.0


class ImagePreprocessor:
    """PIL のみを使った画像前処理クラス。

    使い方:
        proc = ImagePreprocessor()
        result = proc.process(image_bytes, doc_type_hint="receipt")
        ocr_ready_image = result.pil_image
    """

    TARGET_HEIGHT = 2000   # 縦方向の目標ピクセル数
    MIN_HEIGHT    = 800    # 最低解像度

    def __init__(
        self,
        enhance_thermal: bool = True,
        auto_rotate: bool = True,
        denoise_level: int = 2,
    ) -> None:
        self.enhance_thermal = enhance_thermal
        self.auto_rotate = auto_rotate
        self.denoise_level = denoise_level

    # ──────────────────────────────────────────────────────────────
    # パブリック API
    # ──────────────────────────────────────────────────────────────

    def process(
        self,
        image_input: bytes | str | Path | np.ndarray,
        doc_type_hint: str | None = None,
    ) -> PreprocessResult:
        """メイン前処理パイプライン（PIL 実装）。"""
        pil_img = self._load_pil(image_input)
        original_size = (pil_img.height, pil_img.width)
        applied: list[str] = []

        # ── EXIF 回転補正 ─────────────────────────────────────────
        pil_img = ImageOps.exif_transpose(pil_img)
        applied.append("exif_transpose")

        # ── 解像度正規化 ──────────────────────────────────────────
        if pil_img.height < self.MIN_HEIGHT:
            scale = self.MIN_HEIGHT / pil_img.height
            new_w = int(pil_img.width * scale)
            new_h = int(pil_img.height * scale)
            pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
            applied.append(f"upscale_{scale:.1f}x")

        # ── グレースケール変換 ────────────────────────────────────
        gray = pil_img.convert("L")

        # ── 感熱紙検出 ────────────────────────────────────────────
        arr = np.array(gray)
        is_thermal = bool(np.mean(arr) > 180 and np.std(arr) < 60)
        if is_thermal:
            applied.append("thermal_detected")

        # ── ノイズ除去 ────────────────────────────────────────────
        if self.denoise_level >= 1:
            gray = gray.filter(ImageFilter.MedianFilter(size=3))
            applied.append("median_filter")

        # ── コントラスト強調（感熱紙） ────────────────────────────
        if is_thermal and self.enhance_thermal:
            gray = ImageOps.autocontrast(gray, cutoff=2)
            gray = ImageEnhance.Contrast(gray).enhance(1.5)
            applied.append("thermal_enhance")

        # ── 書類種別別処理 ────────────────────────────────────────
        if doc_type_hint == "handwritten":
            gray = ImageEnhance.Sharpness(gray).enhance(2.5)
            gray = ImageEnhance.Contrast(gray).enhance(1.3)
            applied.append("handwritten_enhance")
        elif doc_type_hint in ("invoice", "card_statement"):
            gray = ImageEnhance.Sharpness(gray).enhance(1.8)
            applied.append("printed_enhance")

        # ── 二値化（Pillow: threshold 128） ───────────────────────
        binary = gray.point(lambda p: 255 if p > 128 else 0, "L")
        applied.append("threshold")

        # ── 余白追加 ──────────────────────────────────────────────
        padded = ImageOps.expand(binary, border=20, fill=255)
        applied.append("border")

        final_arr = np.array(padded)
        confidence = self._estimate_quality(final_arr)

        return PreprocessResult(
            image=final_arr,
            pil_image=padded,
            applied_steps=applied,
            original_size=original_size,
            final_size=(padded.height, padded.width),
            is_thermal_paper=is_thermal,
            confidence=confidence,
        )

    def process_pdf_page(self, page_image: np.ndarray, page_num: int = 0) -> PreprocessResult:
        """PDFページ画像の前処理。"""
        return self.process(page_image, doc_type_hint="invoice")

    # ──────────────────────────────────────────────────────────────
    # プライベートメソッド
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _load_pil(src: bytes | str | Path | np.ndarray) -> Image.Image:
        """様々な入力形式から PIL Image に変換する。"""
        if isinstance(src, np.ndarray):
            return Image.fromarray(src).convert("RGB")
        if isinstance(src, (str, Path)):
            return Image.open(str(src)).convert("RGB")
        if isinstance(src, bytes):
            return Image.open(io.BytesIO(src)).convert("RGB")
        raise TypeError(f"未対応の入力型: {type(src)}")

    @staticmethod
    def _estimate_quality(arr: np.ndarray) -> float:
        """処理済み画像の品質スコアを推定する（0.0〜1.0）。"""
        if arr.size == 0:
            return 0.0
        white_ratio = float(np.mean(arr > 128))
        # 白が多すぎる(空白) or 黒が多すぎる(印刷物)は低スコア
        score = 1.0 - abs(white_ratio - 0.7) * 2
        return max(0.0, min(1.0, score))


# ── ユーティリティ関数 ────────────────────────────────────────────

def image_to_bytes(img: np.ndarray, fmt: str = "PNG") -> bytes:
    """NumPy配列を PNG/JPEG バイト列に変換する。"""
    pil = Image.fromarray(img)
    buf = io.BytesIO()
    pil.save(buf, format=fmt)
    return buf.getvalue()


def bytes_to_pil(data: bytes) -> Image.Image:
    """バイト列を PIL Image に変換する。"""
    return Image.open(io.BytesIO(data)).convert("RGB")
