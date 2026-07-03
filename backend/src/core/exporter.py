"""会計ソフト連携エクスポートモジュール。

対応フォーマット:
  - freee       : freee会計 仕訳インポート CSV
  - money_forward: マネーフォワード クラウド会計 仕訳帳 CSV
  - yayoi       : 弥生会計 仕訳日記帳 CSV
  - generic_csv : 汎用 CSV（任意の会計ソフト向け）
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.models import Document, ExtractedData


def _safe_date(dt: datetime | None, fmt: str = "%Y/%m/%d") -> str:
    return dt.strftime(fmt) if dt else ""


def _safe_amount(v: float | None) -> str:
    if v is None:
        return ""
    return str(int(v)) if v == int(v) else f"{v:.2f}"


# ─────────────────────────────────────────────────────────────────────
# freee 会計 仕訳インポート CSV
# https://support.freee.co.jp/hc/ja/articles/202615354
# ─────────────────────────────────────────────────────────────────────
FREEE_HEADERS = [
    "管理番号", "取引日", "借方勘定科目", "借方税区分", "借方金額(円)",
    "借方税額", "貸方勘定科目", "貸方税区分", "貸方金額(円)", "貸方税額",
    "摘要", "仕訳メモ", "タグ", "MF取引ID",
]


def export_freee(docs: list[tuple["Document", "ExtractedData"]]) -> bytes:
    """freee 会計向け仕訳 CSV を生成する。

    Args:
        docs: (Document, ExtractedData) のリスト

    Returns:
        UTF-8-BOM CSV バイト列
    """
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
    writer.writerow(FREEE_HEADERS)

    for doc, ex in docs:
        if ex is None:
            continue
        tax_label = "課税仕入10%" if (ex.tax_amount_10 or 0) > 0 else (
            "課税仕入8%軽" if (ex.tax_amount_8 or 0) > 0 else "課税仕入10%"
        )
        tax_amount = (ex.tax_amount_10 or 0) + (ex.tax_amount_8 or 0)

        writer.writerow([
            str(doc.id)[:8],                    # 管理番号（ID の先頭8文字）
            _safe_date(ex.transaction_date),    # 取引日
            ex.account_title or "消耗品費",     # 借方勘定科目
            tax_label,                          # 借方税区分
            _safe_amount(ex.total_amount),      # 借方金額
            _safe_amount(tax_amount) if tax_amount else "",  # 借方税額
            "現金" if ex.payment_method == "現金" else "未払金",  # 貸方
            "",                                 # 貸方税区分
            _safe_amount(ex.total_amount),      # 貸方金額
            "",                                 # 貸方税額
            ex.vendor_name or "",               # 摘要
            doc.original_filename,              # 仕訳メモ
            "",                                 # タグ
            "",                                 # MF取引ID
        ])

    return buf.getvalue().encode("utf-8-sig")  # BOM付き UTF-8


# ─────────────────────────────────────────────────────────────────────
# マネーフォワード クラウド会計
# ─────────────────────────────────────────────────────────────────────
MF_HEADERS = [
    "日付", "借方勘定科目", "借方補助科目", "借方部門", "借方税区分",
    "借方金額", "借方税額", "貸方勘定科目", "貸方補助科目", "貸方部門",
    "貸方税区分", "貸方金額", "貸方税額", "摘要", "号",
]


def export_money_forward(docs: list[tuple["Document", "ExtractedData"]]) -> bytes:
    """マネーフォワード クラウド会計向け仕訳 CSV を生成する。"""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
    writer.writerow(MF_HEADERS)

    for doc, ex in docs:
        if ex is None:
            continue
        tax_label = "課税仕入10%" if (ex.tax_amount_10 or 0) > 0 else "課税仕入8%"
        tax_amount = (ex.tax_amount_10 or 0) + (ex.tax_amount_8 or 0)

        writer.writerow([
            _safe_date(ex.transaction_date),
            ex.account_title or "消耗品費",
            "",                                 # 補助科目
            "",                                 # 部門
            tax_label,
            _safe_amount(ex.total_amount),
            _safe_amount(tax_amount) if tax_amount else "",
            "現金" if ex.payment_method == "現金" else "未払金",
            "", "",                             # 補助・部門
            "",                                 # 貸方税区分
            _safe_amount(ex.total_amount),
            "",
            f"{ex.vendor_name or ''} {doc.original_filename}".strip(),
            str(doc.id)[:8],
        ])

    return buf.getvalue().encode("utf-8-sig")


# ─────────────────────────────────────────────────────────────────────
# 弥生会計（仕訳日記帳形式）
# ─────────────────────────────────────────────────────────────────────
YAYOI_HEADERS = [
    "識別フラグ", "伝票No", "決算", "取引日付",
    "借方勘定科目", "借方補助科目", "借方部門", "借方金額", "借方消費税額",
    "借方税区分", "借方税込区分",
    "貸方勘定科目", "貸方補助科目", "貸方部門", "貸方金額", "貸方消費税額",
    "貸方税区分", "貸方税込区分",
    "摘要", "番号", "期日", "タイプ", "生成元",
]


def export_yayoi(docs: list[tuple["Document", "ExtractedData"]]) -> bytes:
    """弥生会計向け仕訳日記帳 CSV を生成する。"""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)

    # 弥生は先頭に固定ヘッダー行が必要
    writer.writerow(['"', "弥生会計", "インポート用", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])
    writer.writerow(["*", "伝票No", "決算", "取引日付",
                     "借方勘定科目", "借方補助科目", "借方部門", "借方金額", "借方消費税額",
                     "借方税区分", "借方税込区分",
                     "貸方勘定科目", "貸方補助科目", "貸方部門", "貸方金額", "貸方消費税額",
                     "貸方税区分", "貸方税込区分",
                     "摘要", "番号", "期日", "タイプ", "生成元"])

    for i, (doc, ex) in enumerate(docs, 1):
        if ex is None:
            continue
        tax_code = "10" if (ex.tax_amount_10 or 0) > 0 else "11"  # 10=課税10%, 11=軽減8%
        tax_amount = (ex.tax_amount_10 or 0) + (ex.tax_amount_8 or 0)
        credit_account = "現金" if ex.payment_method == "現金" else "未払金"

        writer.writerow([
            "2",                                    # 識別フラグ: 2=仕訳
            str(i).zfill(6),                        # 伝票No
            "0",                                    # 決算: 0=通常
            _safe_date(ex.transaction_date),        # 取引日付
            ex.account_title or "消耗品費",          # 借方勘定科目
            "", "",                                  # 補助・部門
            _safe_amount(ex.total_amount),           # 借方金額
            _safe_amount(tax_amount) if tax_amount else "0",  # 借方消費税額
            tax_code,                               # 借方税区分
            "1",                                    # 借方税込区分: 1=税込
            credit_account,                         # 貸方勘定科目
            "", "",
            _safe_amount(ex.total_amount),
            "0",
            "0",
            "0",
            ex.vendor_name or "",                   # 摘要
            "", "", "", "",
        ])

    return buf.getvalue().encode("cp932")  # 弥生は Shift-JIS (cp932)


# ─────────────────────────────────────────────────────────────────────
# 汎用 CSV（任意の会計ソフト向け）
# ─────────────────────────────────────────────────────────────────────
GENERIC_HEADERS = [
    "管理ID", "ファイル名", "書類種別", "取引日", "取引先名", "取引先住所",
    "取引先電話番号", "適格請求書番号", "請求書番号",
    "合計金額(税込)", "税抜金額", "消費税額(10%)", "消費税額(8%)",
    "支払方法", "勘定科目", "備考", "OCR信頼度", "承認者", "承認日時",
]


def export_generic_csv(docs: list[tuple["Document", "ExtractedData"]]) -> bytes:
    """汎用 CSV を生成する。最も多くのフィールドを含む標準形式。"""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
    writer.writerow(GENERIC_HEADERS)

    for doc, ex in docs:
        approved_at = doc.approved_at.strftime("%Y/%m/%d %H:%M") if doc.approved_at else ""
        row = [
            str(doc.id),
            doc.original_filename,
            doc.doc_type,
            _safe_date(ex.transaction_date if ex else None),
            ex.vendor_name or "" if ex else "",
            ex.vendor_address or "" if ex else "",
            ex.vendor_phone or "" if ex else "",
            ex.vendor_registration_no or "" if ex else "",
            ex.invoice_number or "" if ex else "",
            _safe_amount(ex.total_amount if ex else None),
            _safe_amount(ex.subtotal_amount if ex else None),
            _safe_amount(ex.tax_amount_10 if ex else None),
            _safe_amount(ex.tax_amount_8 if ex else None),
            ex.payment_method or "" if ex else "",
            ex.account_title or "" if ex else "",
            ex.note or "" if ex else "",
            f"{doc.ocr_confidence:.2f}" if doc.ocr_confidence else "",
            doc.approved_by or "",
            approved_at,
        ]
        writer.writerow(row)

    return buf.getvalue().encode("utf-8-sig")


# ─────────────────────────────────────────────────────────────────────
# エクスポート関数ディスパッチャ
# ─────────────────────────────────────────────────────────────────────

def export(
    docs: list[tuple["Document", "ExtractedData"]],
    fmt: str,
) -> tuple[bytes, str, str]:
    """指定フォーマットでエクスポートする。

    Returns:
        (CSVバイト列, ファイル名, Content-Type)
    """
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    dispatch = {
        "freee":          (export_freee,          f"freee_{now}.csv",    "text/csv; charset=utf-8"),
        "money_forward":  (export_money_forward,  f"mf_{now}.csv",       "text/csv; charset=utf-8"),
        "yayoi":          (export_yayoi,          f"yayoi_{now}.csv",    "text/csv; charset=shift_jis"),
        "generic_csv":    (export_generic_csv,    f"generic_{now}.csv",  "text/csv; charset=utf-8"),
    }
    if fmt not in dispatch:
        raise ValueError(f"未対応のエクスポート形式: {fmt}")
    func, filename, content_type = dispatch[fmt]
    return func(docs), filename, content_type
