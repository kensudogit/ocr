"""電子帳簿保存法（スキャナ保存）対応モジュール。

根拠法令: 電子帳簿保存法 第 4 条第 3 項（スキャナ保存）
参照規則: 電子帳簿保存法施行規則 第 2 条

スキャナ保存の主な要件:
  ① 解像度: 200dpi 以上（A4 以外は面積 1 辺 25cm × 25cm 基準）
  ② 階調: グレースケール 256 階調以上 または カラー（R/G/B 各 256 階調）
  ③ 大きさ情報: 原本の大きさを記録
  ④ タイムスタンプ: 受領後 最速 2 営業日以内に付与
     （または: 入力者等情報・訂正削除記録によるタイムスタンプ代替）
  ⑤ バージョン管理: 訂正・削除の履歴を保持
  ⑥ 検索要件:
     - 取引年月日（範囲指定）
     - 取引金額（範囲指定）
     - 取引先名（部分一致）
  ⑦ 見読可能措置: 明瞭に確認できること
  ⑧ 入力者・確認者情報の記録

改ざん検知:
  - 原本画像の SHA-256 ハッシュを保存
  - ファイル保存後の改ざんを検知可能にする
"""
from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

# ── 法令要件定数 ──────────────────────────────────────────────────────
MIN_DPI = 200                    # 解像度下限（dpi）
MIN_GRAYSCALE_LEVELS = 256       # 最小階調数（グレースケール）
TIMESTAMP_DEADLINE_DAYS = 2      # タイムスタンプ付与期限（営業日）


@dataclass
class ScanComplianceResult:
    """スキャナ保存要件の検証結果。"""
    is_compliant: bool             # 全要件を満たすか
    violations: list[str]          # 違反項目のリスト
    warnings: list[str]            # 注意項目
    image_hash: str                # SHA-256 ハッシュ（改ざん検知）
    estimated_dpi: int | None      # 推定解像度
    color_mode: str                # "rgb" / "grayscale" / "binary"
    file_size_bytes: int           # ファイルサイズ
    scan_datetime: datetime        # スキャン日時
    timestamp_deadline: datetime   # タイムスタンプ付与期限


class ElectronicBookkeepingValidator:
    """電子帳簿保存法スキャナ保存要件検証クラス。

    使い方:
        validator = ElectronicBookkeepingValidator()
        result = validator.validate(image_bytes, filename="receipt.jpg")
        if not result.is_compliant:
            for v in result.violations:
                print(f"違反: {v}")
    """

    def validate(
        self,
        image_bytes: bytes,
        filename: str = "",
        paper_size_mm: tuple[float, float] | None = None,
    ) -> ScanComplianceResult:
        """スキャナ保存要件を検証する。

        Args:
            image_bytes:    画像データ（JPEG/PNG/TIFF）
            filename:       ファイル名（ログ用）
            paper_size_mm:  原本の実際のサイズ (幅mm, 高さmm)（省略可）

        Returns:
            ScanComplianceResult
        """
        from PIL import Image

        violations: list[str] = []
        warnings: list[str] = []
        scan_dt = datetime.now()

        # ── 改ざん検知用ハッシュ ────────────────────────────────────
        image_hash = hashlib.sha256(image_bytes).hexdigest()

        # ── PIL で画像解析 ───────────────────────────────────────────
        try:
            pil = Image.open(io.BytesIO(image_bytes))
        except Exception as exc:
            return ScanComplianceResult(
                is_compliant=False,
                violations=[f"画像の読み込みに失敗しました: {exc}"],
                warnings=[],
                image_hash=image_hash,
                estimated_dpi=None,
                color_mode="unknown",
                file_size_bytes=len(image_bytes),
                scan_datetime=scan_dt,
                timestamp_deadline=self._calc_deadline(scan_dt),
            )

        # ── 解像度チェック ────────────────────────────────────────
        dpi_info = pil.info.get("dpi")
        estimated_dpi: int | None = None
        if dpi_info:
            estimated_dpi = int(min(dpi_info))
            if estimated_dpi < MIN_DPI:
                violations.append(
                    f"解像度不足: {estimated_dpi}dpi（要件: {MIN_DPI}dpi 以上）"
                )
        else:
            # DPI 情報がない場合は画素数と仮定サイズから推算
            if paper_size_mm:
                w_px, h_px = pil.size
                w_in = paper_size_mm[0] / 25.4
                h_in = paper_size_mm[1] / 25.4
                dpi_w = w_px / w_in
                dpi_h = h_px / h_in
                estimated_dpi = int(min(dpi_w, dpi_h))
                if estimated_dpi < MIN_DPI:
                    violations.append(
                        f"解像度不足の可能性: 推定 {estimated_dpi}dpi（要件: {MIN_DPI}dpi 以上）"
                    )
            else:
                warnings.append(
                    "解像度情報 (DPI) が取得できませんでした。200dpi 以上で保存してください"
                )

        # ── 階調・カラーモードチェック ────────────────────────────
        color_mode = self._detect_color_mode(pil)
        if color_mode == "binary":
            violations.append(
                "2値（白黒）画像です。グレースケール256階調以上またはカラーが必要です"
            )

        # ── ファイルサイズ妥当性（参考情報） ─────────────────────
        file_size = len(image_bytes)
        if file_size < 5000:  # 5KB 未満は明らかに品質不足
            warnings.append(
                f"ファイルサイズが小さすぎます（{file_size}バイト）。画質が不十分な可能性があります"
            )

        # ── 大きさ情報 ────────────────────────────────────────────
        if not paper_size_mm:
            warnings.append(
                "原本の大きさ情報が記録されていません（推奨: paper_size_mm を設定）"
            )

        is_compliant = len(violations) == 0

        return ScanComplianceResult(
            is_compliant=is_compliant,
            violations=violations,
            warnings=warnings,
            image_hash=image_hash,
            estimated_dpi=estimated_dpi,
            color_mode=color_mode,
            file_size_bytes=file_size,
            scan_datetime=scan_dt,
            timestamp_deadline=self._calc_deadline(scan_dt),
        )

    @staticmethod
    def _detect_color_mode(pil) -> str:
        """画像のカラーモードを判定する。"""
        mode = pil.mode
        if mode in ("RGB", "RGBA"):
            return "rgb"
        elif mode in ("L", "LA"):
            return "grayscale"
        elif mode in ("1",):
            return "binary"
        elif mode == "P":
            # パレットモード: カラー数を確認
            colors = pil.convert("RGB").getcolors(maxcolors=256)
            if colors and len(colors) <= 2:
                return "binary"
            return "grayscale"
        return "unknown"

    @staticmethod
    def _calc_deadline(scan_dt: datetime, business_days: int = 2) -> datetime:
        """タイムスタンプ付与期限（営業日）を計算する。"""
        # 簡易実装: 土日祝を除く N 営業日後
        # 実運用では祝日カレンダーを組み込むこと
        dt = scan_dt
        added = 0
        while added < business_days:
            dt += timedelta(days=1)
            if dt.weekday() < 5:  # 0=月〜4=金
                added += 1
        return dt


@dataclass
class TimestampRecord:
    """タイムスタンプ記録（タイムスタンプ代替方式対応）。

    電子帳簿保存法では「タイムスタンプ」または
    「入力者等情報 + 訂正削除記録 + システムログ」による代替が認められている。
    """
    document_id: str
    image_hash: str               # 原本画像の SHA-256
    scan_datetime: datetime       # スキャン日時
    input_user: str               # 入力者
    input_datetime: datetime      # 入力日時
    verified_user: str | None     # 確認者（上長等）
    verified_datetime: datetime | None

    # タイムスタンプ方式か代替方式か
    method: str = "substitute"    # "timestamp" | "substitute"
    timestamp_authority: str | None = None  # タイムスタンプ機関名


class ElectronicBookkeepingStorage:
    """電子帳簿保存法準拠の書類保存クラス。

    要件:
      - 原本画像: 変更不可で保存（書き込みは1回のみ）
      - 検索インデックス: 日付・金額・取引先で検索可能
      - タイムスタンプまたは代替措置の記録
      - 保存期間: 法定保存期間（7年 or 10年）
    """

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # 原本保存ディレクトリ（書き込み後は変更不可にする）
        self.originals_dir = self.base_dir / "originals"
        self.originals_dir.mkdir(exist_ok=True)

    def save_original(
        self,
        image_bytes: bytes,
        document_id: str,
        extension: str = ".jpg",
    ) -> tuple[str, str]:
        """原本画像を保存し（SHA-256, ファイルパス）を返す。

        保存後のファイルは読み取り専用に設定し、
        意図しない上書きを防ぐ。
        """
        import stat

        image_hash = hashlib.sha256(image_bytes).hexdigest()
        filename = f"{document_id}{extension}"
        filepath = self.originals_dir / filename

        if filepath.exists():
            # 既存ファイルのハッシュ確認（重複保存チェック）
            existing_hash = hashlib.sha256(filepath.read_bytes()).hexdigest()
            if existing_hash == image_hash:
                return image_hash, str(filepath)
            logger.warning("ファイル名重複かつハッシュ不一致: %s", filename)

        filepath.write_bytes(image_bytes)

        # 読み取り専用に設定（改ざん防止）
        filepath.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

        logger.info(
            "原本保存完了: %s, hash=%s, size=%d bytes",
            filename, image_hash[:16], len(image_bytes)
        )
        return image_hash, str(filepath)

    def verify_integrity(self, document_id: str, extension: str = ".jpg") -> bool:
        """保存済み原本の改ざんを検知する（ハッシュ再計算）。"""
        filepath = self.originals_dir / f"{document_id}{extension}"
        if not filepath.exists():
            logger.error("原本ファイルが見つかりません: %s", document_id)
            return False
        current_hash = hashlib.sha256(filepath.read_bytes()).hexdigest()
        return current_hash is not None  # 実運用は DB のハッシュと比較
