"""データベースモデル定義。

テーブル構成:
  - clients          : 顧問先（税務事務所のクライアント）
  - documents        : アップロードされた書類メタデータ
  - extracted_data   : OCR で抽出した仕訳データ（日付・金額・店舗名等）
  - line_items       : 明細行（品目・単価・数量）
  - journal_history  : 過去の承認済み仕訳（ルールエンジン学習用）
  - export_logs      : 会計ソフト向けエクスポート履歴
  - batch_jobs       : バッチ処理ジョブ管理
  - audit_logs       : 操作ログ・監査証跡（セキュリティ・電帳法対応）
  - scan_timestamps  : スキャンタイムスタンプ記録（電子帳簿保存法対応）
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.database import Base


# ── 定数 ─────────────────────────────────────────────────────────

class ConfidenceTierValue:
    AUTO_CONFIRMED = "auto_confirmed"
    NEEDS_REVIEW   = "needs_review"
    MANUAL_INPUT   = "manual_input"


class DocType:
    RECEIPT      = "receipt"       # レシート（感熱紙）
    HANDWRITTEN  = "handwritten"   # 手書き領収書
    INVOICE      = "invoice"       # 請求書
    CARD_STMT    = "card_statement" # カード明細
    BANK_STMT    = "bank_statement" # 通帳・銀行明細
    UNKNOWN      = "unknown"

class DocStatus:
    UPLOADED     = "uploaded"      # アップロード済み（未処理）
    PROCESSING   = "processing"    # OCR処理中
    PENDING      = "pending"       # OCR完了・確認待ち
    APPROVED     = "approved"      # 確認済み・承認済み
    REJECTED     = "rejected"      # 差し戻し
    EXPORTED     = "exported"      # エクスポート済み

class ExportFormat:
    FREEE        = "freee"         # freee会計 CSV
    MONEY_FORWARD = "money_forward" # マネーフォワード CSV
    YAYOI        = "yayoi"         # 弥生会計 CSV
    GENERIC_CSV  = "generic_csv"   # 汎用 CSV
    MJS          = "mjs"           # MJS（ミロク情報サービス）

class TaxType:
    STANDARD_10  = "standard_10"  # 標準税率 10%
    REDUCED_8    = "reduced_8"    # 軽減税率 8%
    EXEMPT       = "exempt"       # 非課税
    MIXED        = "mixed"        # 混在


# ── Clients テーブル ──────────────────────────────────────────────────
class Client(Base):
    """顧問先（税理士事務所のクライアント）。

    顧問先ごとに勘定科目ルール・会計ソフト連携設定を保持する。
    """
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), unique=True)       # 顧問先名
    code: Mapped[str | None] = mapped_column(String(50), unique=True) # 顧問先コード
    fiscal_year_end: Mapped[int | None] = mapped_column(Integer)       # 決算月（1〜12）

    # ── 会計ソフト連携設定 ────────────────────────────────────────
    accounting_software: Mapped[str | None] = mapped_column(String(30))
    # "freee" | "money_forward" | "yayoi" | "generic_csv"
    freee_company_id: Mapped[str | None] = mapped_column(String(50))
    freee_access_token: Mapped[str | None] = mapped_column(String(2000))
    freee_refresh_token: Mapped[str | None] = mapped_column(String(2000))
    freee_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── タイムスタンプ ────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    documents: Mapped[list["Document"]] = relationship("Document", back_populates="client")
    journal_history: Mapped[list["JournalHistory"]] = relationship(
        "JournalHistory", back_populates="client"
    )


# ── Documents テーブル ────────────────────────────────────────────
class Document(Base):
    """アップロードされた書類のメタデータ。

    1ファイル = 1レコード。PDFの場合は複数ページを持つ。
    """
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── ファイル情報 ──────────────────────────────────────────
    original_filename: Mapped[str] = mapped_column(String(500))
    stored_filename: Mapped[str] = mapped_column(String(500), unique=True)
    file_path: Mapped[str] = mapped_column(String(1000))
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    mime_type: Mapped[str] = mapped_column(String(100))
    page_count: Mapped[int] = mapped_column(Integer, default=1)

    # ── 書類分類 ──────────────────────────────────────────────
    doc_type: Mapped[str] = mapped_column(
        String(50), default=DocType.UNKNOWN
    )
    doc_type_confidence: Mapped[float | None] = mapped_column(Numeric(5, 3))

    # ── 処理状態 ──────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), default=DocStatus.UPLOADED, index=True
    )
    ocr_engine_used: Mapped[str | None] = mapped_column(String(50))
    ocr_confidence: Mapped[float | None] = mapped_column(Numeric(5, 3))
    ocr_raw_text: Mapped[str | None] = mapped_column(Text)  # OCR 生テキスト
    processing_error: Mapped[str | None] = mapped_column(Text)

    # ── 画像前処理情報 ────────────────────────────────────────
    preprocessing_applied: Mapped[dict | None] = mapped_column(JSONB)

    # ── 顧問先 ───────────────────────────────────────────────────
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True, index=True
    )

    # ── 信頼度スコアリング ─────────────────────────────────────────
    confidence_tier: Mapped[str] = mapped_column(
        String(20), default=ConfidenceTierValue.NEEDS_REVIEW, index=True
    )
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 3))
    arithmetic_check_ok: Mapped[bool | None] = mapped_column(Boolean)
    arithmetic_diff: Mapped[float | None] = mapped_column(Numeric(14, 2))
    review_flags: Mapped[list | None] = mapped_column(JSONB)
    vlm_model_used: Mapped[str | None] = mapped_column(String(50))

    # ── バッチ処理 ────────────────────────────────────────────
    batch_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batch_jobs.id"), nullable=True, index=True
    )

    # ── タイムスタンプ ────────────────────────────────────────
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(100))

    # ── リレーション ──────────────────────────────────────────
    client: Mapped["Client | None"] = relationship("Client", back_populates="documents")
    extracted: Mapped["ExtractedData | None"] = relationship(
        "ExtractedData", back_populates="document", uselist=False, cascade="all, delete-orphan"
    )
    line_items: Mapped[list[LineItem]] = relationship(
        "LineItem", back_populates="document", cascade="all, delete-orphan"
    )
    export_logs: Mapped[list[ExportLog]] = relationship(
        "ExportLog", back_populates="document"
    )
    batch_job: Mapped[BatchJob | None] = relationship("BatchJob", back_populates="documents")


# ── ExtractedData テーブル ─────────────────────────────────────────
class ExtractedData(Base):
    """OCR で抽出した仕訳データ（1書類 = 1レコード）。

    確認・修正後に approved フラグが立つ。
    """
    __tablename__ = "extracted_data"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )

    # ── 基本仕訳データ ────────────────────────────────────────
    transaction_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vendor_name: Mapped[str | None] = mapped_column(String(500))        # 店舗名 / 取引先名
    vendor_address: Mapped[str | None] = mapped_column(String(1000))   # 住所
    vendor_phone: Mapped[str | None] = mapped_column(String(50))       # 電話番号
    vendor_registration_no: Mapped[str | None] = mapped_column(String(50))  # 適格請求書番号（T + 13桁）

    # ── 金額 ─────────────────────────────────────────────────
    total_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))  # 合計金額（税込）
    subtotal_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))  # 小計（税抜）
    tax_amount_10: Mapped[float | None] = mapped_column(Numeric(14, 2))  # 消費税（10%）
    tax_amount_8: Mapped[float | None] = mapped_column(Numeric(14, 2))   # 消費税（8%）
    taxable_10: Mapped[float | None] = mapped_column(Numeric(14, 2))     # 課税対象額（10%）
    taxable_8: Mapped[float | None] = mapped_column(Numeric(14, 2))      # 課税対象額（8%）
    tax_type: Mapped[str] = mapped_column(String(20), default=TaxType.STANDARD_10)

    # ── 書類固有情報 ──────────────────────────────────────────
    invoice_number: Mapped[str | None] = mapped_column(String(200))  # 請求書番号
    payment_method: Mapped[str | None] = mapped_column(String(50))   # 支払方法（現金/カード等）
    payment_due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 支払期限
    note: Mapped[str | None] = mapped_column(Text)  # 備考

    # ── 会計分類 ──────────────────────────────────────────────
    account_title: Mapped[str | None] = mapped_column(String(100))   # 勘定科目
    account_code: Mapped[str | None] = mapped_column(String(20))     # 勘定科目コード
    cost_center: Mapped[str | None] = mapped_column(String(100))     # 部門・コストセンター
    tax_category: Mapped[str | None] = mapped_column(String(50))     # 税区分

    # ── 信頼度 ────────────────────────────────────────────────
    confidence_scores: Mapped[dict | None] = mapped_column(JSONB)
    # 例: {"date": 0.92, "amount": 0.99, "vendor": 0.75}

    # ── 確認フラグ ────────────────────────────────────────────
    is_manually_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── タイムスタンプ ────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── リレーション ──────────────────────────────────────────
    document: Mapped[Document] = relationship("Document", back_populates="extracted")


# ── LineItems テーブル ─────────────────────────────────────────────
class LineItem(Base):
    """請求書・レシートの明細行データ。"""
    __tablename__ = "line_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)  # 行順序

    description: Mapped[str | None] = mapped_column(String(500))   # 品目・摘要
    quantity: Mapped[float | None] = mapped_column(Numeric(10, 3)) # 数量
    unit: Mapped[str | None] = mapped_column(String(50))           # 単位
    unit_price: Mapped[float | None] = mapped_column(Numeric(14, 2))  # 単価
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2))      # 金額
    tax_rate: Mapped[float | None] = mapped_column(Numeric(5, 3))     # 税率（0.10 or 0.08）
    account_title: Mapped[str | None] = mapped_column(String(100))    # 勘定科目

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    document: Mapped[Document] = relationship("Document", back_populates="line_items")


# ── ExportLog テーブル ─────────────────────────────────────────────
class ExportLog(Base):
    """会計ソフト向けエクスポート履歴。"""
    __tablename__ = "export_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    export_format: Mapped[str] = mapped_column(String(30))  # freee / money_forward / etc.
    exported_file: Mapped[str | None] = mapped_column(String(1000))  # 出力ファイルパス
    exported_by: Mapped[str | None] = mapped_column(String(100))
    exported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    document: Mapped[Document] = relationship("Document", back_populates="export_logs")
    freee_deal_id: Mapped[str | None] = mapped_column(String(100))  # freee API 取引ID


# ── JournalHistory テーブル ────────────────────────────────────────────
class JournalHistory(Base):
    """承認済み仕訳の履歴テーブル（ルールエンジン学習用）。

    担当者が承認した仕訳を記録し、同一顧問先の将来仕訳を
    自動サジェストするために使用する。
    """
    __tablename__ = "journal_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    # ── 学習データ ────────────────────────────────────────────────
    vendor_name: Mapped[str] = mapped_column(String(500), index=True)
    account_title: Mapped[str] = mapped_column(String(100))
    tax_category: Mapped[str] = mapped_column(String(50))
    payment_method: Mapped[str | None] = mapped_column(String(50))
    amount_range: Mapped[str | None] = mapped_column(String(20))
    # 金額帯: "0-1000" / "1001-10000" / "10001+"

    # ── 使用統計 ──────────────────────────────────────────────────
    use_count: Mapped[int] = mapped_column(Integer, default=1)  # この組み合わせが使われた回数
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    client: Mapped["Client | None"] = relationship("Client", back_populates="journal_history")


# ── BatchJob テーブル ──────────────────────────────────────────────
class BatchJob(Base):
    """バッチアップロード・処理ジョブ管理。

    複数ファイルを一括アップロードした際のジョブ単位を管理する。
    """
    __tablename__ = "batch_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_name: Mapped[str | None] = mapped_column(String(200))  # 例: "2024年3月分 一括OCR"
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending / running / completed / failed / partial

    total_files: Mapped[int] = mapped_column(Integer, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, default=0)
    failed_files: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(100))

    documents: Mapped[list[Document]] = relationship("Document", back_populates="batch_job")


# ── AuditLog テーブル ─────────────────────────────────────────────────
class AuditLog(Base):
    """操作ログ・監査証跡テーブル。

    電子帳簿保存法の「入力者等情報の記録」および
    セキュリティ監査のための操作ログを保存する。

    保存対象:
      - 書類アップロード・承認・修正・削除
      - 仕訳データの変更前後
      - エクスポート操作
      - 認証イベント（ログイン・失敗）
      - AI リクエスト（どのモデルを使用したか）
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # ── 操作情報 ──────────────────────────────────────────────────
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    # 例: "document.approve" / "journal.edit" / "auth.login"

    user_id: Mapped[str | None] = mapped_column(String(100), index=True)
    # 操作ユーザー（将来: UUID への変更を推奨）

    resource_type: Mapped[str | None] = mapped_column(String(50))
    # 操作対象種別: "document" / "journal" / "client"

    resource_id: Mapped[str | None] = mapped_column(String(100), index=True)
    # 操作対象の ID（UUID 文字列）

    status: Mapped[str] = mapped_column(String(20), default="success")
    # "success" / "failure" / "warning"

    ip_address: Mapped[str | None] = mapped_column(String(45))
    # IPv4（15桁）または IPv6（39桁）

    # ── 変更詳細（変更前後の値） ──────────────────────────────────
    detail: Mapped[dict | None] = mapped_column(JSONB)
    # 例: {"changes": {"account_title": {"before": "消耗品費", "after": "旅費交通費"}}}


# ── ScanTimestamp テーブル（電子帳簿保存法） ──────────────────────────────
class ScanTimestamp(Base):
    """スキャンタイムスタンプ記録テーブル（電子帳簿保存法 スキャナ保存要件）。

    スキャナ保存要件（電子帳簿保存法施行規則第 2 条）:
      - 受領後2営業日以内のタイムスタンプ付与
      - タイムスタンプ代替方式: 入力者情報 + 訂正削除記録
      - 原本画像のハッシュ（改ざん検知）
    """
    __tablename__ = "scan_timestamps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True
    )

    # ── 原本保全 ──────────────────────────────────────────────────
    image_hash: Mapped[str] = mapped_column(String(64))    # SHA-256 ハッシュ（64桁）
    scan_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scan_dpi: Mapped[int | None] = mapped_column(Integer)  # スキャン解像度
    color_mode: Mapped[str | None] = mapped_column(String(20))  # "rgb" / "grayscale"
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)

    # ── 入力者情報（タイムスタンプ代替方式） ────────────────────
    input_user: Mapped[str] = mapped_column(String(100))
    input_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_user: Mapped[str | None] = mapped_column(String(100))
    verified_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── タイムスタンプ方式 ────────────────────────────────────────
    method: Mapped[str] = mapped_column(String(20), default="substitute")
    # "timestamp": タイムスタンプ機関利用
    # "substitute": 代替方式（入力者情報 + システムログ）
    timestamp_authority: Mapped[str | None] = mapped_column(String(100))
    timestamp_token: Mapped[str | None] = mapped_column(Text)  # TSA トークン

    # ── 検証結果 ──────────────────────────────────────────────────
    is_compliant: Mapped[bool] = mapped_column(Boolean, default=False)
    compliance_violations: Mapped[list | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
