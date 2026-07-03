"""画像前処理モジュール。

税理士事務所が扱う書類に特化した前処理パイプラインを提供する。

対応書類の特性と対処:
  - 感熱紙レシート: 低コントラスト・背景グレー → CLAHE でコントラスト強調
  - 手書き領収書: 手ブレ・薄い筆跡 → シャープニング・二値化
  - カード明細: 細かい文字・印刷ムラ → ガンマ補正・解像度アップ
  - 皺・歪み: スキャン前提だが撮影も想定 → 透視変換・歪み補正
  - サイズばらつき: A4〜小型レシート → 解像度正規化
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

# OpenCV is optional: some Railway base images miss required shared libs.
# When unavailable the preprocessor silently falls back to PIL-only mode.
try:
    import cv2  # type: ignore[import]
    _CV2 = True
except (ImportError, OSError):
    cv2 = None  # type: ignore[assignment]
    _CV2 = False


@dataclass
class PreprocessResult:
    """前処理結果。"""
    image: np.ndarray                          # 処理済み画像（NumPy配列）
    pil_image: Image.Image                     # PIL イメージ（OCRエンジン用）
    applied_steps: list[str] = field(default_factory=list)  # 適用した処理ステップ
    skew_angle: float = 0.0                    # 検出された傾き角度（度）
    original_size: tuple[int, int] = (0, 0)   # 元の画像サイズ (H, W)
    final_size: tuple[int, int] = (0, 0)       # 処理後のサイズ (H, W)
    is_thermal_paper: bool = False             # 感熱紙と判定したか
    confidence: float = 1.0                   # 処理品質スコア（0-1）


class ImagePreprocessor:
    """書類画像前処理クラス。

    使い方:
        proc = ImagePreprocessor()
        result = proc.process(image_bytes, doc_type_hint="receipt")
        ocr_ready_image = result.pil_image
    """

    # 感熱紙判定のしきい値（平均輝度が高く、分散が低い = グレー背景）
    THERMAL_PAPER_MEAN_THRESHOLD = 200
    THERMAL_PAPER_STD_THRESHOLD  = 40
    # OCR に最適な解像度（DPI換算想定）
    TARGET_DPI_HEIGHT = 2000   # 縦方向の目標ピクセル数（A4基準）
    MIN_HEIGHT = 800           # 最低解像度（これ以下はアップスケール）

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
    # パブリックAPI
    # ──────────────────────────────────────────────────────────────

    def process(
        self,
        image_input: bytes | str | Path | np.ndarray,
        doc_type_hint: str | None = None,
    ) -> PreprocessResult:
        """メイン前処理パイプライン。

        Args:
            image_input: 画像バイト列 / ファイルパス / NumPy配列
            doc_type_hint: "receipt" / "invoice" / "handwritten" / None

        Returns:
            PreprocessResult: 処理済み画像と適用ステップのログ
        """
        if not _CV2:
            return self._process_pil_only(image_input)

        img = self._load_image(image_input)
        original_size = img.shape[:2]
        applied: list[str] = []

        # ── Step 1: EXIF 回転補正 ──────────────────────────────
        img = self._correct_exif_rotation(image_input, img)
        applied.append("exif_rotation")

        # ── Step 2: グレースケール化（処理用） ─────────────────
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # ── Step 3: 感熱紙判定 ─────────────────────────────────
        is_thermal = self._detect_thermal_paper(gray)
        if is_thermal:
            applied.append("thermal_detected")

        # ── Step 4: 解像度正規化（低解像度画像のアップスケール） ─
        if gray.shape[0] < self.MIN_HEIGHT:
            scale = self.MIN_HEIGHT / gray.shape[0]
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            img  = cv2.resize(img,  None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            applied.append(f"upscale_{scale:.1f}x")

        # ── Step 5: ノイズ除去 ─────────────────────────────────
        gray = self._denoise(gray, level=self.denoise_level)
        applied.append(f"denoise_l{self.denoise_level}")

        # ── Step 6: 感熱紙コントラスト強調 ─────────────────────
        if is_thermal and self.enhance_thermal:
            gray = self._enhance_thermal_paper(gray)
            applied.append("thermal_enhance")

        # ── Step 7: 歪み補正（傾き検出・補正） ─────────────────
        skew_angle = 0.0
        if self.auto_rotate:
            skew_angle = self._detect_skew(gray)
            if abs(skew_angle) > 0.3:  # 0.3度以上で補正実施
                gray = self._deskew(gray, skew_angle)
                applied.append(f"deskew_{skew_angle:.1f}deg")

        # ── Step 8: 書類種別に応じた追加処理 ─────────────────
        if doc_type_hint == "handwritten":
            gray = self._enhance_handwritten(gray)
            applied.append("handwritten_enhance")
        elif doc_type_hint in ("invoice", "card_statement"):
            gray = self._enhance_printed(gray)
            applied.append("printed_enhance")

        # ── Step 9: 適応的二値化（OCR精度向上） ─────────────────
        binary = self._adaptive_threshold(gray)
        applied.append("adaptive_threshold")

        # ── Step 10: 周囲の余白を追加（OCRエンジンへの配慮） ───
        binary = self._add_border(binary)
        applied.append("add_border")

        final_size = binary.shape[:2]
        pil_img = Image.fromarray(binary)

        # 品質スコア（コントラスト・鮮明度の簡易評価）
        confidence = self._estimate_quality(binary)

        return PreprocessResult(
            image=binary,
            pil_image=pil_img,
            applied_steps=applied,
            skew_angle=skew_angle,
            original_size=original_size,
            final_size=final_size,
            is_thermal_paper=is_thermal,
            confidence=confidence,
        )

    def _process_pil_only(
        self,
        image_input: bytes | str | Path | np.ndarray,
    ) -> PreprocessResult:
        """OpenCV が利用できない場合の PIL フォールバック前処理。"""
        if isinstance(image_input, np.ndarray):
            pil_img = Image.fromarray(image_input).convert("RGB")
        elif isinstance(image_input, (str, Path)):
            pil_img = Image.open(str(image_input)).convert("RGB")
        else:
            pil_img = Image.open(io.BytesIO(image_input)).convert("RGB")  # type: ignore[arg-type]

        original_size = (pil_img.height, pil_img.width)

        # Minimum upscale
        if pil_img.height < self.MIN_HEIGHT:
            scale = self.MIN_HEIGHT / pil_img.height
            pil_img = pil_img.resize(
                (int(pil_img.width * scale), int(pil_img.height * scale)),
                Image.LANCZOS,
            )

        gray = pil_img.convert("L")
        # Light sharpening
        enhanced = ImageEnhance.Sharpness(gray).enhance(2.0)
        arr = np.array(enhanced)
        return PreprocessResult(
            image=arr,
            pil_image=enhanced,
            applied_steps=["pil_fallback"],
            original_size=original_size,
            final_size=(enhanced.height, enhanced.width),
            confidence=0.75,
        )

    def process_pdf_page(self, page_image: np.ndarray, page_num: int = 0) -> PreprocessResult:
        """PDFページ画像の前処理。

        pdf2image で変換したページ画像を受け取り標準パイプラインを適用する。
        """
        return self.process(page_image, doc_type_hint="invoice")

    # ──────────────────────────────────────────────────────────────
    # プライベートメソッド群
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _load_image(src: bytes | str | Path | np.ndarray) -> np.ndarray:
        """様々な入力形式から OpenCV BGR 画像に変換する。"""
        if isinstance(src, np.ndarray):
            return src.copy()
        if isinstance(src, (str, Path)):
            img = cv2.imread(str(src))  # type: ignore[union-attr]
            if img is None:
                raise ValueError(f"画像を読み込めませんでした: {src}")
            return img
        if isinstance(src, bytes):
            arr = np.frombuffer(src, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # type: ignore[union-attr]
            if img is None:
                pil_img = Image.open(io.BytesIO(src)).convert("RGB")
                img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)  # type: ignore[union-attr]
            return img
        raise TypeError(f"未対応の入力型: {type(src)}")

    @staticmethod
    def _correct_exif_rotation(src: bytes | str | Path | np.ndarray, img: np.ndarray) -> np.ndarray:
        """スマートフォン撮影画像の EXIF 回転情報を補正する。"""
        if not isinstance(src, (bytes, str, Path)):
            return img
        try:
            raw = src if isinstance(src, bytes) else Path(src).read_bytes()
            pil_img = Image.open(io.BytesIO(raw))
            exif = pil_img._getexif()  # type: ignore[attr-defined]
            if not exif:
                return img
            # EXIF タグ 0x0112 = Orientation
            orientation = exif.get(274, 1)
            rotations = {3: 180, 6: 270, 8: 90}
            angle = rotations.get(orientation, 0)
            if angle:
                pil_img = pil_img.rotate(angle, expand=True)
                img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        except Exception:
            pass
        return img

    @staticmethod
    def _detect_thermal_paper(gray: np.ndarray) -> bool:
        """感熱紙レシートを検出する。

        特徴: 背景が薄いグレー（平均輝度が高い）、コントラストが低い（標準偏差が小さい）。
        """
        mean = float(np.mean(gray))
        std  = float(np.std(gray))
        return mean > 180 and std < 60

    @staticmethod
    def _denoise(gray: np.ndarray, level: int) -> np.ndarray:
        """ノイズ除去。level に応じて強度を変える。

        level 0: 処理なし
        level 1: ガウシアンブラー（軽微）
        level 2: FastNlMeansDenoising（中）
        level 3: Bilateral Filter（強・エッジ保存）
        """
        if level == 0:
            return gray
        if level == 1:
            return cv2.GaussianBlur(gray, (3, 3), 0)
        if level == 2:
            return cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)
        # level 3
        denoised = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)
        return denoised

    @staticmethod
    def _enhance_thermal_paper(gray: np.ndarray) -> np.ndarray:
        """感熱紙レシートのコントラスト強調。

        CLAHE（適応的ヒストグラム平坦化）を適用し、
        薄くなった文字を鮮明にする。
        """
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        # ガンマ補正（暗い領域を明るく）
        gamma = 0.7
        lut = np.array([
            min(255, int((i / 255.0) ** gamma * 255))
            for i in range(256)
        ], dtype=np.uint8)
        return cv2.LUT(enhanced, lut)

    @staticmethod
    def _detect_skew(gray: np.ndarray) -> float:
        """Hough 変換で文書の傾き角度を検出する。

        Returns:
            傾き角度（度）。正: 時計回り, 負: 反時計回り
        """
        # エッジ検出
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        # Hough 直線検出（確率的Hough変換）
        lines = cv2.HoughLinesP(
            edges, rho=1, theta=np.pi / 180,
            threshold=80, minLineLength=gray.shape[1] // 4,
            maxLineGap=20,
        )
        if lines is None or len(lines) == 0:
            return 0.0

        angles: list[float] = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 - x1 == 0:
                continue
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
            # 水平に近い線のみ使用（±45度以内）
            if -45 < angle < 45:
                angles.append(angle)

        if not angles:
            return 0.0
        return float(np.median(angles))

    @staticmethod
    def _deskew(gray: np.ndarray, angle: float) -> np.ndarray:
        """傾き補正を適用する。"""
        h, w = gray.shape[:2]
        cx, cy = w // 2, h // 2
        M = cv2.getRotationMatrix2D((cx, cy), -angle, 1.0)
        # 余白は白（255）で埋める
        rotated = cv2.warpAffine(
            gray, M, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=255,
        )
        return rotated

    @staticmethod
    def _enhance_handwritten(gray: np.ndarray) -> np.ndarray:
        """手書き文字の強調処理。

        薄い鉛筆書き・ペン書きのコントラストを上げ、
        文字輪郭をシャープにする。
        """
        # Morphology: 文字を太くする（膨張処理）
        kernel = np.ones((2, 2), np.uint8)
        dilated = cv2.dilate(gray, kernel, iterations=1)
        # シャープニング
        kernel_sharpen = np.array([
            [-1, -1, -1],
            [-1,  9, -1],
            [-1, -1, -1],
        ])
        sharpened = cv2.filter2D(dilated, -1, kernel_sharpen)
        # CLAHE で局所コントラスト強調
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(sharpened)

    @staticmethod
    def _enhance_printed(gray: np.ndarray) -> np.ndarray:
        """印刷文書（請求書・カード明細）の強調処理。

        印刷ムラ・低品質スキャンに対応する。
        """
        # 軽微なシャープニング
        kernel = np.array([
            [ 0, -1,  0],
            [-1,  5, -1],
            [ 0, -1,  0],
        ])
        return cv2.filter2D(gray, -1, kernel)

    @staticmethod
    def _adaptive_threshold(gray: np.ndarray) -> np.ndarray:
        """適応的二値化。

        局所的な照明差に強い適応的二値化を適用する。
        背景が不均一なレシートに特に効果的。
        """
        # Otsu の二値化（まず全体の閾値を求める）
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # 適応的二値化（ブロックサイズは画像の1/50を目安）
        block_size = max(11, (gray.shape[1] // 50) | 1)  # 奇数にする
        adaptive = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=block_size,
            C=10,
        )
        # Otsu と適応的の AND で精度向上
        result = cv2.bitwise_and(otsu, adaptive)
        return result

    @staticmethod
    def _add_border(img: np.ndarray, size: int = 20) -> np.ndarray:
        """OCR精度向上のため白い余白を追加する。"""
        return cv2.copyMakeBorder(
            img, size, size, size, size,
            cv2.BORDER_CONSTANT, value=255,
        )

    @staticmethod
    def _estimate_quality(img: np.ndarray) -> float:
        """処理済み画像の品質スコアを推定する（0.0〜1.0）。

        Laplacian の分散 = 鮮明度の指標。数値が高いほど鮮明。
        """
        laplacian_var = cv2.Laplacian(img, cv2.CV_64F).var()
        # 典型的な良質画像: var > 500, 低品質: var < 50
        score = min(1.0, laplacian_var / 1000.0)
        return float(score)


# ── ユーティリティ関数 ────────────────────────────────────────────

def image_to_bytes(img: np.ndarray, format: str = "PNG") -> bytes:
    """NumPy配列を PNG/JPEG バイト列に変換する。"""
    pil = Image.fromarray(img)
    buf = io.BytesIO()
    pil.save(buf, format=format)
    return buf.getvalue()


def bytes_to_pil(data: bytes) -> Image.Image:
    """バイト列を PIL Image に変換する。"""
    return Image.open(io.BytesIO(data)).convert("RGB")
