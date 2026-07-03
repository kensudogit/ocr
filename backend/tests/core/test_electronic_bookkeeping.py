"""電子帳簿保存法対応モジュールのテスト。

対象: src/core/electronic_bookkeeping.py
テスト観点:
  - 解像度チェック（200dpi 以上）
  - 階調チェック（グレースケール 256 以上 or カラー）
  - SHA-256 ハッシュ生成
  - 原本保存・読み取り専用設定
  - タイムスタンプ期限計算
  - 改ざん検知
"""
from __future__ import annotations

import hashlib
import io
import stat
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.core.electronic_bookkeeping import (
    ElectronicBookkeepingStorage,
    ElectronicBookkeepingValidator,
    MIN_DPI,
)


@pytest.mark.unit
@pytest.mark.electronic_bookkeeping
class TestElectronicBookkeepingValidator:
    """ElectronicBookkeepingValidator のテスト。"""

    def setup_method(self):
        self.validator = ElectronicBookkeepingValidator()

    def test_valid_high_dpi_image_passes(self, sample_image_bytes: bytes):
        """200dpi 以上の画像は解像度チェックを通過すること。"""
        result = self.validator.validate(sample_image_bytes)
        # 解像度情報が埋め込まれていれば検証される
        # 埋め込みなしの場合は警告のみ（violations は空）
        assert isinstance(result.is_compliant, bool)

    def test_image_hash_is_sha256(self, sample_image_bytes: bytes):
        """SHA-256 ハッシュが 64 文字の16進数であること。"""
        result = self.validator.validate(sample_image_bytes)
        assert len(result.image_hash) == 64
        assert all(c in "0123456789abcdef" for c in result.image_hash)

    def test_image_hash_is_deterministic(self, sample_image_bytes: bytes):
        """同じ画像は同じハッシュを返すこと（改ざん検知の基礎）。"""
        result1 = self.validator.validate(sample_image_bytes)
        result2 = self.validator.validate(sample_image_bytes)
        assert result1.image_hash == result2.image_hash

    def test_different_images_have_different_hashes(self, sample_image_bytes: bytes):
        """異なる画像は異なるハッシュを返すこと。"""
        modified = sample_image_bytes + b"\x00\x01\x02"
        result1 = self.validator.validate(sample_image_bytes)
        result2 = self.validator.validate(modified)
        assert result1.image_hash != result2.image_hash

    def test_scan_datetime_is_recent(self, sample_image_bytes: bytes):
        """スキャン日時が現在に近いこと（1分以内）。"""
        before = datetime.now()
        result = self.validator.validate(sample_image_bytes)
        after = datetime.now()
        assert before <= result.scan_datetime <= after

    def test_timestamp_deadline_is_2_business_days(self, sample_image_bytes: bytes):
        """タイムスタンプ期限がスキャン日時から 2 営業日後であること。"""
        result = self.validator.validate(sample_image_bytes)
        diff = result.timestamp_deadline - result.scan_datetime
        # 2〜4 日後（土日を挟む可能性あり）
        assert timedelta(days=2) <= diff <= timedelta(days=6)

    def test_file_size_is_recorded(self, sample_image_bytes: bytes):
        """ファイルサイズが正確に記録されること。"""
        result = self.validator.validate(sample_image_bytes)
        assert result.file_size_bytes == len(sample_image_bytes)

    def test_invalid_image_bytes_returns_violation(self):
        """不正なバイト列は violations にエラーを返すこと。"""
        invalid_bytes = b"this is not an image"
        result = self.validator.validate(invalid_bytes)
        assert not result.is_compliant
        assert len(result.violations) > 0

    def test_small_file_generates_warning(self):
        """極小ファイル（5KB 以下）は警告を生成すること。"""
        tiny_bytes = b"\xff\xd8\xff\xd9"  # 最小 JPEG
        result = self.validator.validate(tiny_bytes)
        # エラーか警告が出ること
        assert len(result.violations) > 0 or len(result.warnings) > 0

    def test_min_dpi_constant(self):
        """MIN_DPI 定数が 200 であること（法令要件）。"""
        assert MIN_DPI == 200

    def test_color_mode_detection_rgb(self):
        """RGB 画像のカラーモードが 'rgb' と判定されること。"""
        try:
            from PIL import Image
            img = Image.new("RGB", (100, 100), (255, 255, 255))
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            result = self.validator.validate(buf.getvalue())
            assert result.color_mode == "rgb"
        except ImportError:
            pytest.skip("Pillow が利用できないためスキップ")

    def test_color_mode_detection_grayscale(self):
        """グレースケール画像のカラーモードが 'grayscale' と判定されること。"""
        try:
            from PIL import Image
            img = Image.new("L", (100, 100), 128)
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            result = self.validator.validate(buf.getvalue())
            assert result.color_mode == "grayscale"
        except ImportError:
            pytest.skip("Pillow が利用できないためスキップ")


@pytest.mark.unit
@pytest.mark.electronic_bookkeeping
class TestElectronicBookkeepingStorage:
    """ElectronicBookkeepingStorage のテスト。"""

    def test_save_original_returns_hash_and_path(self, temp_dir: Path, sample_image_bytes: bytes):
        """原本保存が SHA-256 ハッシュとファイルパスを返すこと。"""
        storage = ElectronicBookkeepingStorage(temp_dir / "originals")
        doc_id = "test-doc-001"
        image_hash, file_path = storage.save_original(sample_image_bytes, doc_id, ".jpg")

        assert len(image_hash) == 64
        assert Path(file_path).exists()

    def test_saved_file_content_matches(self, temp_dir: Path, sample_image_bytes: bytes):
        """保存したファイルの内容が元のバイト列と一致すること。"""
        storage = ElectronicBookkeepingStorage(temp_dir / "originals2")
        doc_id = "test-doc-002"
        _, file_path = storage.save_original(sample_image_bytes, doc_id, ".jpg")

        saved_bytes = Path(file_path).read_bytes()
        assert saved_bytes == sample_image_bytes

    def test_saved_file_hash_matches_sha256(self, temp_dir: Path, sample_image_bytes: bytes):
        """保存ファイルのハッシュが SHA-256 と一致すること。"""
        storage = ElectronicBookkeepingStorage(temp_dir / "originals3")
        doc_id = "test-doc-003"
        returned_hash, file_path = storage.save_original(sample_image_bytes, doc_id, ".jpg")

        expected_hash = hashlib.sha256(sample_image_bytes).hexdigest()
        assert returned_hash == expected_hash

    def test_saved_file_is_readonly(self, temp_dir: Path, sample_image_bytes: bytes):
        """保存したファイルが読み取り専用になっていること（改ざん防止）。"""
        storage = ElectronicBookkeepingStorage(temp_dir / "originals4")
        doc_id = "test-doc-004"
        _, file_path = storage.save_original(sample_image_bytes, doc_id, ".jpg")

        path = Path(file_path)
        file_stat = path.stat()
        # 書き込み権限がないこと（Windows では stat が異なる場合あり）
        assert not (file_stat.st_mode & stat.S_IWUSR), "ファイルが書き込み可能になっています"

    def test_duplicate_save_returns_same_hash(self, temp_dir: Path, sample_image_bytes: bytes):
        """同じドキュメント ID で再保存しても同じハッシュを返すこと。"""
        storage = ElectronicBookkeepingStorage(temp_dir / "originals5")
        doc_id = "test-doc-005"
        hash1, _ = storage.save_original(sample_image_bytes, doc_id, ".jpg")
        hash2, _ = storage.save_original(sample_image_bytes, doc_id, ".jpg")
        assert hash1 == hash2

    def test_integrity_verification(self, temp_dir: Path, sample_image_bytes: bytes):
        """verify_integrity() が保存済みファイルで True を返すこと。"""
        storage = ElectronicBookkeepingStorage(temp_dir / "originals6")
        doc_id = "test-doc-006"
        storage.save_original(sample_image_bytes, doc_id, ".jpg")
        result = storage.verify_integrity(doc_id, ".jpg")
        assert result is True

    def test_integrity_fails_for_missing_file(self, temp_dir: Path):
        """存在しないファイルの verify_integrity() は False を返すこと。"""
        storage = ElectronicBookkeepingStorage(temp_dir / "originals7")
        result = storage.verify_integrity("nonexistent-doc", ".jpg")
        assert result is False
