"""OCR エンジン統合モジュール。

エンジン優先順位:
  1. PaddleOCR  - ローカル実行・日本語対応・無料
  2. Google Cloud Vision API - 手書き文字に強い（API キー設定時のみ）

信頼度が低い場合（< 0.7）は自動的に Google Vision にフォールバックする。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from src.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class OcrWord:
    """OCR 認識した単語の情報。"""
    text: str
    confidence: float
    bbox: list[list[int]]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] 四角形座標


@dataclass
class OcrResult:
    """OCR エンジンの認識結果。"""
    full_text: str                         # 全文テキスト（改行区切り）
    words: list[OcrWord] = field(default_factory=list)  # 単語別の認識結果
    engine_used: str = "unknown"           # 使用したエンジン
    overall_confidence: float = 0.0       # 全体の信頼度（0-1）
    language_detected: str = "ja"
    processing_time_ms: float = 0.0

    @property
    def lines(self) -> list[str]:
        """テキストを行リストに変換する。"""
        return [ln for ln in self.full_text.splitlines() if ln.strip()]


class OcrEngine:
    """OCR エンジンの統合クラス。

    使い方:
        engine = OcrEngine()
        result = await engine.recognize(pil_image)
        print(result.full_text)
    """

    def __init__(self) -> None:
        self._paddle = None
        self._google_client = None
        self._paddle_initialized = False
        self._google_initialized = False

    # ──────────────────────────────────────────────────────────────
    # パブリック API
    # ──────────────────────────────────────────────────────────────

    async def recognize(
        self,
        image: Image.Image | np.ndarray,
        engine: str | None = None,
        doc_type_hint: str | None = None,
    ) -> OcrResult:
        """OCR 認識を実行する。

        Args:
            image:       PIL Image または NumPy配列（グレースケール推奨）
            engine:      "paddle" / "google" / "auto"（None の場合は設定値を使用）
            doc_type_hint: "handwritten" の場合は Google Vision を優先

        Returns:
            OcrResult: 認識テキスト・単語リスト・信頼度
        """
        import time
        start = time.perf_counter()

        engine = engine or settings.ocr_engine
        img_array = self._to_numpy(image)

        # 手書き書類は Google Vision 優先
        if doc_type_hint == "handwritten" and settings.google_vision_api_key:
            engine = "google"

        result: OcrResult | None = None

        if engine in ("paddle", "auto"):
            result = await self._run_paddle(img_array)

        # auto モードで信頼度が低い場合は Google にフォールバック
        if (
            engine == "auto"
            and result is not None
            and result.overall_confidence < 0.70
            and settings.google_vision_api_key
        ):
            logger.info(
                "PaddleOCR 信頼度 %.2f < 0.70 → Google Vision にフォールバック",
                result.overall_confidence,
            )
            google_result = await self._run_google(img_array)
            if google_result.overall_confidence > result.overall_confidence:
                result = google_result

        if engine == "google":
            result = await self._run_google(img_array)

        if result is None:
            result = OcrResult(full_text="", engine_used="none", overall_confidence=0.0)

        result.processing_time_ms = (time.perf_counter() - start) * 1000
        return result

    # ──────────────────────────────────────────────────────────────
    # PaddleOCR
    # ──────────────────────────────────────────────────────────────

    async def _run_paddle(self, img: np.ndarray) -> OcrResult:
        """PaddleOCR でテキスト認識する。"""
        paddle = self._get_paddle()
        if paddle is None:
            return OcrResult(full_text="", engine_used="paddle_unavailable", overall_confidence=0.0)

        import asyncio
        try:
            # PaddleOCR は同期なので executor で実行
            loop = asyncio.get_event_loop()
            raw_result = await loop.run_in_executor(None, lambda: paddle.ocr(img, cls=True))
        except Exception as exc:
            logger.error("PaddleOCR 実行エラー: %s", exc)
            return OcrResult(full_text="", engine_used="paddle_error", overall_confidence=0.0)

        return self._parse_paddle_result(raw_result)

    def _get_paddle(self):
        """PaddleOCR インスタンスを遅延初期化する。"""
        if self._paddle_initialized:
            return self._paddle
        self._paddle_initialized = True
        try:
            from paddleocr import PaddleOCR
            # use_angle_cls=True: 180度回転テキストを認識
            # lang="japan": 日本語モデル
            self._paddle = PaddleOCR(
                use_angle_cls=True,
                lang="japan",
                use_gpu=False,
                show_log=False,
                rec_batch_num=8,
            )
            logger.info("PaddleOCR 初期化完了")
        except ImportError:
            logger.warning("PaddleOCR が見つかりません。pip install paddleocr を実行してください")
            self._paddle = None
        except Exception as exc:
            logger.error("PaddleOCR 初期化エラー: %s", exc)
            self._paddle = None
        return self._paddle

    @staticmethod
    def _parse_paddle_result(raw: list | None) -> OcrResult:
        """PaddleOCR の出力をパースして OcrResult に変換する。"""
        if not raw or not raw[0]:
            return OcrResult(full_text="", engine_used="paddle", overall_confidence=0.0)

        words: list[OcrWord] = []
        lines_text: list[str] = []
        confidences: list[float] = []

        # PaddleOCR 出力形式: [[bbox, (text, confidence)], ...]
        for line in raw[0]:
            bbox, (text, conf) = line
            words.append(OcrWord(
                text=text,
                confidence=float(conf),
                bbox=[[int(p[0]), int(p[1])] for p in bbox],
            ))
            lines_text.append(text)
            confidences.append(float(conf))

        full_text = "\n".join(lines_text)
        overall_conf = float(np.mean(confidences)) if confidences else 0.0

        return OcrResult(
            full_text=full_text,
            words=words,
            engine_used="paddle",
            overall_confidence=overall_conf,
        )

    # ──────────────────────────────────────────────────────────────
    # Google Cloud Vision API
    # ──────────────────────────────────────────────────────────────

    async def _run_google(self, img: np.ndarray) -> OcrResult:
        """Google Cloud Vision API でテキスト認識する。"""
        client = self._get_google_client()
        if client is None:
            return OcrResult(full_text="", engine_used="google_unavailable", overall_confidence=0.0)

        import asyncio
        import io as _io

        from PIL import Image as _Image
        pil = _Image.fromarray(img)
        buf = _io.BytesIO()
        pil.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        try:
            from google.cloud.vision import Image as GImage, Feature
            loop = asyncio.get_event_loop()
            g_image = GImage(content=image_bytes)
            feature = Feature(type_=Feature.Type.DOCUMENT_TEXT_DETECTION)
            response = await loop.run_in_executor(
                None,
                lambda: client.annotate_image({"image": g_image, "features": [feature]}),
            )
        except Exception as exc:
            logger.error("Google Vision API エラー: %s", exc)
            return OcrResult(full_text="", engine_used="google_error", overall_confidence=0.0)

        return self._parse_google_result(response)

    def _get_google_client(self):
        """Google Vision クライアントを遅延初期化する。"""
        if self._google_initialized:
            return self._google_client
        self._google_initialized = True
        if not settings.google_vision_api_key:
            return None
        try:
            from google.cloud import vision
            self._google_client = vision.ImageAnnotatorClient()
            logger.info("Google Vision API クライアント初期化完了")
        except ImportError:
            logger.warning("google-cloud-vision が見つかりません")
            self._google_client = None
        except Exception as exc:
            logger.error("Google Vision クライアント初期化エラー: %s", exc)
            self._google_client = None
        return self._google_client

    @staticmethod
    def _parse_google_result(response) -> OcrResult:
        """Google Vision API レスポンスをパースする。"""
        try:
            annotation = response.full_text_annotation
            full_text = annotation.text if annotation else ""
            words: list[OcrWord] = []
            confidences: list[float] = []
            for page in annotation.pages:
                for block in page.blocks:
                    for para in block.paragraphs:
                        for word in para.words:
                            word_text = "".join(s.text for s in word.symbols)
                            conf = float(word.confidence) if word.confidence else 0.8
                            verts = word.bounding_box.vertices
                            bbox = [[v.x, v.y] for v in verts]
                            words.append(OcrWord(text=word_text, confidence=conf, bbox=bbox))
                            confidences.append(conf)
            overall_conf = float(np.mean(confidences)) if confidences else 0.8
            return OcrResult(
                full_text=full_text,
                words=words,
                engine_used="google",
                overall_confidence=overall_conf,
            )
        except Exception as exc:
            logger.error("Google Vision レスポンスパースエラー: %s", exc)
            return OcrResult(full_text="", engine_used="google_parse_error", overall_confidence=0.0)

    # ──────────────────────────────────────────────────────────────
    # ユーティリティ
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _to_numpy(image: Image.Image | np.ndarray) -> np.ndarray:
        """PIL Image を NumPy 配列に変換する。"""
        if isinstance(image, np.ndarray):
            return image
        return np.array(image)
