/**
 * OCR バックエンド API クライアント
 *
 * - ローカル開発: NEXT_PUBLIC_API_URL=http://localhost:8000 (デフォルト)
 * - Railway (統合デプロイ): NEXT_PUBLIC_API_URL=/api
 *   Next.js の rewrite で /api/* → http://127.0.0.1:8000/* にプロキシされる
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── 型定義 ──────────────────────────────────────────────────────────

export interface ExtractedData {
  transaction_date: string | null;
  vendor_name: string | null;
  vendor_address: string | null;
  vendor_phone: string | null;
  vendor_registration_no: string | null;
  total_amount: number | null;
  subtotal_amount: number | null;
  tax_amount_10: number | null;
  tax_amount_8: number | null;
  invoice_number: string | null;
  payment_method: string | null;
  account_title: string | null;
  tax_category: string | null;
  cost_center: string | null;
  note: string | null;
  confidence_scores: Record<string, number> | null;
  is_manually_corrected: boolean;
}

export interface Document {
  id: string;
  original_filename: string;
  stored_filename?: string;
  doc_type: string;
  status: string;
  ocr_confidence: number | null;
  uploaded_at: string;
  processed_at: string | null;
  approved_at: string | null;
  total_amount: number | null;
  vendor_name: string | null;
  transaction_date: string | null;
  // 信頼度スコアリング
  confidence_tier: string;
  confidence_score: number | null;
  arithmetic_check_ok: boolean | null;
  review_flags: string[];
}

export interface DocumentDetail extends Document {
  stored_filename: string;
  file_path: string;
  doc_type_confidence: number | null;
  ocr_engine_used: string | null;
  ocr_raw_text: string | null;
  preprocessing_applied: Record<string, unknown> | null;
  approved_by: string | null;
  extracted: ExtractedData | null;
  line_items: LineItem[];
  export_logs: ExportLog[];
}

export interface LineItem {
  id: string;
  sort_order: number;
  description: string | null;
  quantity: number | null;
  unit: string | null;
  unit_price: number | null;
  amount: number | null;
  tax_rate: number | null;
  account_title: string | null;
}

export interface ExportLog {
  id: string;
  export_format: string;
  exported_at: string;
  row_count: number;
}

export interface DocumentListResponse {
  total: number;
  page: number;
  page_size: number;
  items: Document[];
}

export interface Stats {
  status_breakdown: Record<string, number>;
  doc_type_breakdown: Record<string, number>;
  monthly_upload_count: number;
  total_approved_amount: number;
}

export interface BatchJobStatus {
  job_id: string;
  job_name: string;
  status: string;
  total_files: number;
  processed_files: number;
  failed_files: number;
  progress_percent: number;
  started_at: string | null;
  completed_at: string | null;
}

// ── ユーティリティ ────────────────────────────────────────────────────

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API エラー ${res.status}: ${body}`);
  }
  return res.json();
}

// ── 書類 API ─────────────────────────────────────────────────────────

export const documentsApi = {
  /** 書類一覧取得 */
  list: (params?: {
    status?: string;
    doc_type?: string;
    page?: number;
    page_size?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.doc_type) qs.set("doc_type", params.doc_type);
    if (params?.page) qs.set("page", String(params.page));
    if (params?.page_size) qs.set("page_size", String(params.page_size));
    return request<DocumentListResponse>(`/documents/?${qs}`);
  },

  /** 書類詳細取得 */
  get: (id: string) => request<DocumentDetail>(`/documents/${id}`),

  /** 統計サマリー */
  stats: () => request<Stats>("/documents/stats/summary"),

  /** 抽出データ更新（手動修正） */
  updateExtracted: (id: string, data: Partial<ExtractedData>, correctedBy = "staff") => {
    const qs = new URLSearchParams({ corrected_by: correctedBy });
    return request<{ message: string }>(`/documents/${id}/extracted?${qs}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  },

  /** 承認 */
  approve: (id: string, approvedBy = "staff") => {
    const qs = new URLSearchParams({ approved_by: approvedBy });
    return request<{ message: string }>(`/documents/${id}/approve?${qs}`, { method: "POST" });
  },

  /** 差し戻し */
  reject: (id: string, reason = "") => {
    const qs = new URLSearchParams({ reason });
    return request<{ message: string }>(`/documents/${id}/reject?${qs}`, { method: "POST" });
  },

  /** 削除 */
  delete: (id: string) => request<{ message: string }>(`/documents/${id}`, { method: "DELETE" }),
};

// ── アップロード API ──────────────────────────────────────────────────

export const uploadApi = {
  /** 1ファイルアップロード */
  upload: async (file: File, autoProcess = true): Promise<{ document_id: string; status: string }> => {
    const form = new FormData();
    form.append("file", file);
    const qs = new URLSearchParams({ auto_process: String(autoProcess) });
    return request<{ document_id: string; status: string }>(`/upload/?${qs}`, {
      method: "POST",
      body: form,
    });
  },

  /** 一括アップロード */
  batchUpload: async (
    files: File[],
    jobName = ""
  ): Promise<{ batch_job_id: string; total_files: number }> => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    const qs = new URLSearchParams({ job_name: jobName });
    return request(`/upload/batch?${qs}`, { method: "POST", body: form });
  },

  /** バッチジョブ進捗確認 */
  batchStatus: (jobId: string) => request<BatchJobStatus>(`/upload/batch/${jobId}/status`),

  /** 再処理 */
  reprocess: (id: string) =>
    request<{ message: string; status: string }>(`/upload/${id}/reprocess`, { method: "POST" }),
};

// ── エクスポート API ──────────────────────────────────────────────────

export const exportApi = {
  /** CSVエクスポート（ブラウザダウンロード） */
  export: async (fmt: string, docIds?: string[]) => {
    const qs = new URLSearchParams({ fmt });
    if (docIds?.length) docIds.forEach((id) => qs.append("doc_ids", id));
    const res = await fetch(`${BASE_URL}/export/?${qs}`, { method: "POST" });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`エクスポートエラー: ${body}`);
    }
    // ファイルダウンロード
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="([^"]+)"/);
    const filename = m ? m[1] : `export_${fmt}.csv`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    return filename;
  },

  /** 対応フォーマット一覧 */
  formats: () =>
    request<{
      formats: { id: string; name: string; description: string; encoding: string }[];
    }>("/export/formats"),
};

// ── ヘルパー ─────────────────────────────────────────────────────────

/** ファイルURLを返す（プレビュー用） */
export function fileUrl(storedFilename: string): string {
  return `${BASE_URL}/files/${storedFilename}`;
}

/** 書類種別を日本語ラベルに変換 */
export const DOC_TYPE_LABELS: Record<string, string> = {
  receipt:        "レシート",
  handwritten:    "手書き領収書",
  invoice:        "請求書",
  card_statement: "カード明細",
  bank_statement: "銀行明細",
  unknown:        "不明",
};

/** ステータスを日本語ラベルに変換 */
export const STATUS_LABELS: Record<string, string> = {
  uploaded:   "未処理",
  processing: "処理中",
  pending:    "確認待ち",
  approved:   "承認済み",
  rejected:   "差し戻し",
  exported:   "エクスポート済み",
};

/** ステータスに対応するカラー */
export const STATUS_COLORS: Record<string, string> = {
  uploaded:   "bg-gray-100 text-gray-700",
  processing: "bg-blue-100 text-blue-700",
  pending:    "bg-yellow-100 text-yellow-700",
  approved:   "bg-green-100 text-green-700",
  rejected:   "bg-red-100 text-red-700",
  exported:   "bg-purple-100 text-purple-700",
};

/** 金額を日本円フォーマットに変換 */
export function formatCurrency(amount: number | null | undefined): string {
  if (amount == null) return "—";
  return new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY" }).format(amount);
}

/** 日付を日本語フォーマットに変換 */
export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleDateString("ja-JP", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
  } catch {
    return dateStr;
  }
}
