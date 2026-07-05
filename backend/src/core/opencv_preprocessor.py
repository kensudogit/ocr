"""OpenCV ベースの画像前処理（認識率向上用）。

PIL 前処理に加え、傾き補正・CLAHE・適応的二値化で
レシート・請求書の OCR 精度を向上させる。
OpenCV が未インストールの場合は PIL 前処理にフォールバックする。
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps

from src.core.preprocessor import ImagePreprocessor, PreprocessResult

logger = logging.getLogger(__name__)

_cv2 = None


def opencv_available() -> bool:
    """OpenCV が利用可能かどうか。"""
    global _cv2
    if _cv2 is not None:
        return True
    try:
        import cv2  # noqa: F401

        _cv2 = __import__("cv2")
        return True
    except ImportError:
        return False


def _get_cv2():
    global _cv2
    if _cv2 is None and opencv_available():
        import cv2

        _cv2 = cv2
    return _cv2


@dataclass
class OpenCvPreprocessConfig:
    """OpenCV 前処理パラメータ。"""

    target_min_height: int = 2000
    clahe_clip_limit: float = 2.0
    clahe_grid_size: int = 8
    denoise_strength: int = 10
    adaptive_block_size: int = 31
    adaptive_c: int = 10
    deskew_max_angle: float = 15.0


class OpenCvPreprocessor:
    """OpenCV 前処理パイプライン。"""

    def __init__(self, config: OpenCvPreprocessConfig | None = None) -> None:
        self.config = config or OpenCvPreprocessConfig()
        self._pil_fallback = ImagePreprocessor()

    def process(
        self,
        image_input: bytes,
        doc_type_hint: str | None = None,
    ) -> PreprocessResult:
        """OpenCV で前処理し、失敗時は PIL にフォールバック。"""
        if not opencv_available():
            logger.debug("OpenCV 未インストール — PIL 前処理を使用")
            return self._pil_fallback.process(image_input, doc_type_hint)

        cv2 = _get_cv2()
        applied: list[str] = []

        try:
            pil = Image.open(io.BytesIO(image_input))
            pil = ImageOps.exif_transpose(pil.convert("RGB"))
            original_size = (pil.height, pil.width)
            gray = np.array(pil.convert("L"))
            applied.append("exif_transpose")

            # 解像度正規化
            if gray.shape[0] < self.config.target_min_height:
                scale = self.config.target_min_height / gray.shape[0]
                gray = cv2.resize(
                    gray,
                    None,
                    fx=scale,
                    fy=scale,
                    interpolation=cv2.INTER_CUBIC,
                )
                applied.append(f"upscale_{scale:.1f}x")

            # ノイズ除去
            gray = cv2.fastNlMeansDenoising(
                gray, None, self.config.denoise_strength, 7, 21
            )
            applied.append("nlmeans_denoise")

            # 傾き補正
            angle = self._estimate_skew(cv2, gray)
            if abs(angle) >= 0.3:
                gray = self._rotate(cv2, gray, angle)
                applied.append(f"deskew_{angle:.1f}deg")

            # CLAHE（コントラスト強調）
            clahe = cv2.createCLAHE(
                clipLimit=self.config.clahe_clip_limit,
                tileGridSize=(
                    self.config.clahe_grid_size,
                    self.config.clahe_grid_size,
                ),
            )
            gray = clahe.apply(gray)
            applied.append("clahe")

            # 適応的二値化
            block = self.config.adaptive_block_size
            if block % 2 == 0:
                block += 1
            binary = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                block,
                self.config.adaptive_c,
            )
            applied.append("adaptive_threshold")

            # 余白
            binary = cv2.copyMakeBorder(
                binary, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255
            )
            applied.append("border")

            pil_out = Image.fromarray(binary)
            confidence = self._estimate_quality(binary)

            return PreprocessResult(
                image=binary,
                pil_image=pil_out,
                applied_steps=applied,
                skew_angle=angle,
                original_size=original_size,
                final_size=(binary.shape[0], binary.shape[1]),
                is_thermal_paper=self._detect_thermal(gray),
                confidence=confidence,
            )
        except Exception as exc:
            logger.warning("OpenCV 前処理失敗 — PIL にフォールバック: %s", exc)
            return self._pil_fallback.process(image_input, doc_type_hint)

    def _estimate_skew(self, cv2, gray: np.ndarray) -> float:
        """Hough 変換で傾き角度を推定。"""
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10
        )
        if lines is None or len(lines) == 0:
            return 0.0

        angles: list[float] = []
        for line in lines[:50]:
            x1, y1, x2, y2 = line[0]
            if x2 - x1 == 0:
                continue
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if abs(angle) <= self.config.deskew_max_angle:
                angles.append(angle)

        if not angles:
            return 0.0
        return float(np.median(angles))

    @staticmethod
    def _rotate(cv2, gray: np.ndarray, angle: float) -> np.ndarray:
        h, w = gray.shape[:2]
        center = (w // 2, h // 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(
            gray,
            matrix,
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )

    @staticmethod
    def _detect_thermal(gray: np.ndarray) -> bool:
        return bool(np.mean(gray) > 180 and np.std(gray) < 60)

    @staticmethod
    def _estimate_quality(arr: np.ndarray) -> float:
        if arr.size == 0:
            return 0.0
        white_ratio = float(np.mean(arr > 128))
        score = 1.0 - abs(white_ratio - 0.7) * 2
        return max(0.0, min(1.0, score))
