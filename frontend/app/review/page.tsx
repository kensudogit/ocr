"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  documentsApi,
  formatCurrency,
  formatDate,
  DOC_TYPE_LABELS,
  STATUS_COLORS,
  STATUS_LABELS,
  type Document,
  type DocumentDetail,
  type ExtractedData,
} from "@/lib/api";

// Default to /api so requests are proxied server-side (no CORS in production).
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

// ── 信頼度ティアの表示 ──────────────────────────────────────────────
const TIER_CONFIG = {
  auto_confirmed: {
    label: "自動承認",
    color: "bg-green-100 text-green-700 border-green-200",
    icon: "✅",
    desc: "高精度で自動承認済み",
  },
  needs_review: {
    label: "要確認",
    color: "bg-yellow-100 text-yellow-700 border-yellow-200",
    icon: "⚠️",
    desc: "担当者による確認が必要",
  },
  manual_input: {
    label: "手入力",
    color: "bg-red-100 text-red-700 border-red-200",
    icon: "✏️",
    desc: "精度が低いため手入力が必要",
  },
};

// ── 信頼度スコアバー ────────────────────────────────────────────────
function ConfidenceBar({ score, tier }: { score: number | null; tier: string }) {
  const pct = Math.round((score ?? 0) * 100);
  const color =
    tier === "auto_confirmed" ? "bg-green-400" :
    tier === "needs_review" ? "bg-yellow-400" :
    "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-slate-200 rounded-full h-2">
        <div className={`h-2 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-slate-600 w-8">{pct}%</span>
    </div>
  );
}

// ── 書類一覧（左パネル） ────────────────────────────────────────────
function DocumentList({
  docs,
  selectedId,
  onSelect,
  filter,
  onFilterChange,
}: {
  docs: Document[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  filter: string;
  onFilterChange: (f: string) => void;
}) {
  const filtered = filter === "needs_review_only"
    ? docs.filter((d) => d.confidence_tier === "needs_review" || d.confidence_tier === "manual_input")
    : docs;

  return (
    <div className="bg-white rounded-xl border border-slate-200 overflow-hidden flex flex-col h-full">
      <div className="px-3 py-3 border-b border-slate-100 bg-slate-50 space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-slate-700 text-sm">書類一覧</h2>
          <span className="text-xs text-slate-400">{filtered.length} 件</span>
        </div>
        <div className="flex gap-1">
          {[
            ["all", "すべて"],
            ["needs_review_only", "要確認のみ"],
          ].map(([val, label]) => (
            <button
              key={val}
              onClick={() => onFilterChange(val)}
              className={[
                "flex-1 text-xs py-1 rounded-lg border transition-all",
                filter === val
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white text-slate-600 border-slate-300 hover:bg-slate-50",
              ].join(" ")}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="overflow-y-auto flex-1">
        {filtered.length === 0 ? (
          <div className="text-center py-8 text-slate-400">
            <p className="text-2xl mb-1">✅</p>
            <p className="text-sm">確認待ちの書類はありません</p>
          </div>
        ) : (
          filtered.map((doc) => {
            const tierCfg = TIER_CONFIG[doc.confidence_tier as keyof typeof TIER_CONFIG];
            return (
              <button
                key={doc.id}
                onClick={() => onSelect(doc.id)}
                className={[
                  "w-full text-left px-3 py-3 border-b border-slate-50 transition-all",
                  selectedId === doc.id
                    ? "bg-blue-50 border-l-4 border-l-blue-500"
                    : "hover:bg-slate-50",
                ].join(" ")}
              >
                <p className="text-xs font-medium text-slate-800 truncate">
                  {doc.original_filename}
                </p>
                <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                  {tierCfg && (
                    <span className={`text-xs px-1.5 py-0.5 rounded-full border font-medium ${tierCfg.color}`}>
                      {tierCfg.icon} {tierCfg.label}
                    </span>
                  )}
                  <span className="text-xs text-slate-400">
                    {DOC_TYPE_LABELS[doc.doc_type] ?? doc.doc_type}
                  </span>
                </div>
                {doc.total_amount && (
                  <p className="text-xs font-semibold text-slate-700 mt-0.5">
                    {formatCurrency(doc.total_amount)}
                  </p>
                )}
                {/* 検算エラー表示 */}
                {doc.arithmetic_check_ok === false && (
                  <p className="text-xs text-red-500 mt-0.5">⚡ 検算不一致</p>
                )}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

// ── 原本画像パネル ──────────────────────────────────────────────────
function OriginalImagePanel({ doc }: { doc: DocumentDetail }) {
  const [zoom, setZoom] = useState(1.0);
  const imgSrc = `${API_BASE}/files/${doc.stored_filename}`;

  return (
    <div className="bg-slate-900 rounded-xl overflow-hidden flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 bg-slate-800">
        <span className="text-xs text-slate-300 font-medium">原本画像</span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}
            className="text-slate-400 hover:text-white text-lg leading-none"
          >
            −
          </button>
          <span className="text-xs text-slate-300 w-10 text-center">
            {Math.round(zoom * 100)}%
          </span>
          <button
            onClick={() => setZoom((z) => Math.min(3.0, z + 0.25))}
            className="text-slate-400 hover:text-white text-lg leading-none"
          >
            ＋
          </button>
        </div>
      </div>
      <div className="overflow-auto flex-1 p-3">
        <img
          src={imgSrc}
          alt={doc.original_filename}
          style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}
          className="max-w-none transition-transform"
          onError={(e) => {
            (e.target as HTMLImageElement).src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Crect fill='%23374151' width='200' height='200'/%3E%3Ctext fill='%239CA3AF' x='50%25' y='50%25' text-anchor='middle' dy='.3em'%3E画像なし%3C/text%3E%3C/svg%3E";
          }}
        />
      </div>
    </div>
  );
}

// ── 抽出データ編集フォーム ──────────────────────────────────────────
function ExtractionForm({
  detail,
  onSave,
  onApprove,
  onReject,
}: {
  detail: DocumentDetail;
  onSave: (data: Partial<ExtractedData>) => Promise<void>;
  onApprove: () => Promise<void>;
  onReject: (reason: string) => Promise<void>;
}) {
  const ex = detail.extracted;
  const [form, setForm] = useState<Partial<ExtractedData>>({
    transaction_date: ex?.transaction_date?.split("T")[0] ?? null,
    vendor_name:      ex?.vendor_name ?? null,
    vendor_address:   ex?.vendor_address ?? null,
    vendor_phone:     ex?.vendor_phone ?? null,
    vendor_registration_no: ex?.vendor_registration_no ?? null,
    total_amount:     ex?.total_amount ?? null,
    subtotal_amount:  ex?.subtotal_amount ?? null,
    tax_amount_10:    ex?.tax_amount_10 ?? null,
    tax_amount_8:     ex?.tax_amount_8 ?? null,
    invoice_number:   ex?.invoice_number ?? null,
    payment_method:   ex?.payment_method ?? null,
    account_title:    ex?.account_title ?? null,
    tax_category:     ex?.tax_category ?? null,
    note:             ex?.note ?? null,
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [approving, setApproving] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject] = useState(false);

  const set = (key: keyof ExtractedData, val: string | number | null) => {
    setForm((p) => ({ ...p, [key]: val === "" ? null : val }));
    setSaved(false);
  };

  const totalCalc = (form.subtotal_amount ?? 0) + (form.tax_amount_10 ?? 0) + (form.tax_amount_8 ?? 0);
  const arithmeticOk = !form.total_amount || !form.subtotal_amount ||
    Math.abs(totalCalc - (form.total_amount ?? 0)) <= 1;

  const handleSave = async () => {
    setSaving(true);
    await onSave(form);
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  // 信頼度スコアに応じたフィールドボーダーカラー
  const fieldColor = (field: string) => {
    const c = ex?.confidence_scores?.[field];
    if (c === undefined) return "border-slate-300";
    if (c >= 0.9) return "border-green-300 bg-green-50";
    if (c >= 0.6) return "border-yellow-300 bg-yellow-50";
    return "border-red-300 bg-red-50";
  };

  const ACCOUNT_TITLES = [
    "消耗品費", "旅費交通費", "交際費", "会議費", "通信費",
    "水道光熱費", "広告宣伝費", "新聞図書費", "福利厚生費",
    "外注費", "地代家賃", "修繕費", "雑費",
  ];
  const TAX_CATEGORIES = [
    "課税仕入10%", "課税仕入8%軽減", "非課税", "不課税",
  ];
  const PAYMENT_METHODS = ["現金", "クレジットカード", "電子マネー", "銀行振込", "口座引落"];

  const tierCfg = TIER_CONFIG[detail.confidence_tier as keyof typeof TIER_CONFIG];

  return (
    <div className="space-y-3 h-full overflow-y-auto">
      {/* 信頼度バナー */}
      {tierCfg && (
        <div className={`rounded-xl border p-3 ${tierCfg.color}`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-base">{tierCfg.icon}</span>
              <div>
                <p className="text-sm font-semibold">{tierCfg.label}: {tierCfg.desc}</p>
                {detail.review_flags?.length > 0 && (
                  <ul className="text-xs mt-0.5 space-y-0.5">
                    {detail.review_flags.map((f: string, i: number) => (
                      <li key={i}>• {f}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
            <ConfidenceBar
              score={detail.confidence_score}
              tier={detail.confidence_tier}
            />
          </div>
          {/* 検算結果 */}
          {form.total_amount != null && form.subtotal_amount != null && (
            <div className={`mt-2 text-xs px-2 py-1 rounded ${arithmeticOk ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
              {arithmeticOk ? "✅ 検算OK" : `⚡ 検算不一致: 小計+税=${formatCurrency(totalCalc)} ≠ 合計=${formatCurrency(form.total_amount)}`}
            </div>
          )}
        </div>
      )}

      {/* 入力フォーム */}
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <h3 className="font-semibold text-slate-700 text-sm mb-3">
          抽出データ
          {ex?.is_manually_corrected && (
            <span className="ml-2 text-xs bg-amber-100 text-amber-600 px-1.5 rounded-full">手動修正済み</span>
          )}
        </h3>
        <div className="grid grid-cols-2 gap-3">
          {/* 取引日 */}
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">
              取引日 <span className="text-red-400">*</span>
            </label>
            <input
              type="date"
              value={form.transaction_date?.split("T")[0] ?? ""}
              onChange={(e) => set("transaction_date", e.target.value || null)}
              className={`w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 ${fieldColor("date")}`}
            />
          </div>
          {/* 合計金額 */}
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">
              合計金額（税込）<span className="text-red-400">*</span>
            </label>
            <input
              type="number"
              value={form.total_amount ?? ""}
              onChange={(e) => set("total_amount", e.target.value ? Number(e.target.value) : null)}
              className={`w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 ${fieldColor("amount")}`}
            />
          </div>
          {/* 取引先名 */}
          <div className="col-span-2">
            <label className="block text-xs font-medium text-slate-500 mb-1">
              取引先名 <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={form.vendor_name ?? ""}
              onChange={(e) => set("vendor_name", e.target.value || null)}
              className={`w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 ${fieldColor("vendor")}`}
            />
          </div>
          {/* 税抜金額 */}
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">税抜金額</label>
            <input
              type="number"
              value={form.subtotal_amount ?? ""}
              onChange={(e) => set("subtotal_amount", e.target.value ? Number(e.target.value) : null)}
              className="w-full border border-slate-300 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
          </div>
          {/* 消費税 10% */}
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">消費税（10%）</label>
            <input
              type="number"
              value={form.tax_amount_10 ?? ""}
              onChange={(e) => set("tax_amount_10", e.target.value ? Number(e.target.value) : null)}
              className={`w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 ${fieldColor("tax")}`}
            />
          </div>
          {/* 消費税 8% */}
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">消費税（8% 軽減）</label>
            <input
              type="number"
              value={form.tax_amount_8 ?? ""}
              onChange={(e) => set("tax_amount_8", e.target.value ? Number(e.target.value) : null)}
              className="w-full border border-slate-300 rounded-lg px-2 py-1.5 text-sm"
            />
          </div>
          {/* 勘定科目 */}
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">勘定科目</label>
            <select
              value={form.account_title ?? ""}
              onChange={(e) => set("account_title", e.target.value || null)}
              className="w-full border border-slate-300 rounded-lg px-2 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
            >
              <option value="">— 選択 —</option>
              {ACCOUNT_TITLES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          {/* 税区分 */}
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">税区分</label>
            <select
              value={form.tax_category ?? ""}
              onChange={(e) => set("tax_category", e.target.value || null)}
              className="w-full border border-slate-300 rounded-lg px-2 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
            >
              <option value="">— 選択 —</option>
              {TAX_CATEGORIES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          {/* 適格請求書番号 */}
          <div className="col-span-2">
            <label className="block text-xs font-medium text-slate-500 mb-1">
              適格請求書番号（T + 13桁）
            </label>
            <input
              type="text"
              value={form.vendor_registration_no ?? ""}
              onChange={(e) => set("vendor_registration_no", e.target.value || null)}
              placeholder="T1234567890123"
              className="w-full border border-slate-300 rounded-lg px-2 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
          </div>
          {/* 支払方法 */}
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">支払方法</label>
            <select
              value={form.payment_method ?? ""}
              onChange={(e) => set("payment_method", e.target.value || null)}
              className="w-full border border-slate-300 rounded-lg px-2 py-1.5 text-sm bg-white"
            >
              <option value="">— 選択 —</option>
              {PAYMENT_METHODS.map((m) => <option key={m}>{m}</option>)}
            </select>
          </div>
          {/* 備考 */}
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">備考・摘要</label>
            <input
              type="text"
              value={form.note ?? ""}
              onChange={(e) => set("note", e.target.value || null)}
              className="w-full border border-slate-300 rounded-lg px-2 py-1.5 text-sm"
            />
          </div>
        </div>
        {saved && <p className="text-green-600 text-xs mt-2">✅ 保存しました</p>}
      </div>

      {/* 明細行 */}
      {detail.line_items.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-3">
          <h3 className="font-semibold text-slate-700 text-xs mb-2">明細行</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-400 border-b border-slate-100">
                  <th className="pb-1">品目</th>
                  <th className="pb-1 text-right">数量</th>
                  <th className="pb-1 text-right">単価</th>
                  <th className="pb-1 text-right">金額</th>
                  <th className="pb-1 text-right">税率</th>
                </tr>
              </thead>
              <tbody>
                {detail.line_items.map((item) => (
                  <tr key={item.id} className="border-b border-slate-50">
                    <td className="py-1">{item.description ?? "—"}</td>
                    <td className="py-1 text-right">{item.quantity ?? "—"}</td>
                    <td className="py-1 text-right">{formatCurrency(item.unit_price)}</td>
                    <td className="py-1 text-right font-medium">{formatCurrency(item.amount)}</td>
                    <td className="py-1 text-right">{item.tax_rate ? `${(item.tax_rate * 100).toFixed(0)}%` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* OCR 生テキスト */}
      {detail.ocr_raw_text && (
        <details className="bg-white rounded-xl border border-slate-200 p-3">
          <summary className="cursor-pointer text-xs font-medium text-slate-500">
            VLM 抽出ログを表示
          </summary>
          <pre className="mt-2 text-xs text-slate-500 whitespace-pre-wrap font-mono bg-slate-50 p-2 rounded overflow-auto max-h-40">
            {detail.ocr_raw_text}
          </pre>
        </details>
      )}

      {/* アクションボタン */}
      <div className="flex flex-wrap gap-2 pb-4">
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex-1 min-w-[100px] py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-sm font-medium transition-colors"
        >
          {saving ? "保存中..." : "💾 保存"}
        </button>
        <button
          onClick={async () => { setApproving(true); await handleSave(); await onApprove(); setApproving(false); }}
          disabled={approving || detail.status === "approved"}
          className="flex-1 min-w-[100px] py-2 bg-green-600 hover:bg-green-700 text-white rounded-xl text-sm font-medium disabled:opacity-50"
        >
          {approving ? "..." : "✅ 承認"}
        </button>
        {!showReject ? (
          <button
            onClick={() => setShowReject(true)}
            className="flex-1 min-w-[100px] py-2 bg-red-50 hover:bg-red-100 text-red-600 rounded-xl text-sm border border-red-200"
          >
            ↩️ 差し戻し
          </button>
        ) : (
          <div className="w-full flex gap-2">
            <input
              type="text"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="差し戻し理由（任意）"
              className="flex-1 border border-red-300 rounded-lg px-2 py-1.5 text-sm"
            />
            <button
              onClick={async () => { await onReject(rejectReason); setShowReject(false); }}
              className="px-3 py-1.5 bg-red-600 text-white rounded-lg text-sm"
            >確定</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── メインページ（内部コンポーネント） ──────────────────────────────
function ReviewPageInner() {
  const params = useSearchParams();
  const initialId = params.get("id");

  const [docs, setDocs] = useState<Document[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(initialId);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [listFilter, setListFilter] = useState("needs_review_only");
  const [statusFilter, setStatusFilter] = useState("");
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const loadDocs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await documentsApi.list({
        status: statusFilter || undefined,
        page_size: 200,
      });
      setDocs(res.items);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { loadDocs(); }, [loadDocs]);

  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    setDetailLoading(true);
    documentsApi.get(selectedId).then(setDetail).finally(() => setDetailLoading(false));
  }, [selectedId]);

  const showFeedback = (type: "success" | "error", msg: string) => {
    setFeedback({ type, msg });
    setTimeout(() => setFeedback(null), 3000);
  };

  const handleSave = async (data: Partial<ExtractedData>) => {
    if (!selectedId) return;
    try { await documentsApi.updateExtracted(selectedId, data); showFeedback("success", "保存しました"); }
    catch (e: unknown) { showFeedback("error", e instanceof Error ? e.message : "保存失敗"); }
  };

  const handleApprove = async () => {
    if (!selectedId) return;
    try {
      await documentsApi.approve(selectedId);
      showFeedback("success", "✅ 承認しました。過去仕訳として学習されます");
      await loadDocs();
      setDetail((p) => p ? { ...p, status: "approved" } : p);
    } catch (e: unknown) { showFeedback("error", e instanceof Error ? e.message : "承認失敗"); }
  };

  const handleReject = async (reason: string) => {
    if (!selectedId) return;
    try {
      await documentsApi.reject(selectedId, reason);
      showFeedback("success", "差し戻しました");
      await loadDocs();
      setDetail((p) => p ? { ...p, status: "rejected" } : p);
    } catch (e: unknown) { showFeedback("error", e instanceof Error ? e.message : "差し戻し失敗"); }
  };

  // 確認待ち件数の集計
  const needsReviewCount = docs.filter(
    (d) => d.confidence_tier === "needs_review" || d.confidence_tier === "manual_input"
  ).length;
  const autoCount = docs.filter((d) => d.confidence_tier === "auto_confirmed").length;

  return (
    <div className="space-y-3 h-[calc(100vh-80px)]">
      {/* ヘッダー */}
      <div className="flex items-center flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">確認・修正</h1>
          <p className="text-xs text-slate-500">原本画像と並列表示で正確な確認ができます</p>
        </div>
        <div className="flex items-center gap-2 ml-auto flex-wrap">
          {/* 統計バッジ */}
          <span className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded-full border border-green-200">
            ✅ 自動承認: {autoCount}件
          </span>
          <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-1 rounded-full border border-yellow-200">
            ⚠️ 要確認: {needsReviewCount}件
          </span>
          {/* ステータスフィルター */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="border border-slate-300 rounded-lg px-2 py-1.5 text-xs bg-white"
          >
            <option value="">全ステータス</option>
            <option value="pending">確認待ち</option>
            <option value="approved">承認済み</option>
            <option value="rejected">差し戻し</option>
          </select>
        </div>
      </div>

      {feedback && (
        <div className={`rounded-xl p-2.5 text-sm font-medium ${
          feedback.type === "success" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
        }`}>
          {feedback.msg}
        </div>
      )}

      {/* 3カラムレイアウト: 書類一覧 | 原本画像 | 抽出データ */}
      <div className="grid grid-cols-[220px_1fr_1fr] gap-3 h-[calc(100vh-160px)]">
        {/* 左: 書類一覧 */}
        <div className="overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center h-32 bg-white rounded-xl border border-slate-200">
              <div className="animate-spin h-5 w-5 rounded-full border-2 border-blue-500 border-t-transparent" />
            </div>
          ) : (
            <DocumentList
              docs={docs}
              selectedId={selectedId}
              onSelect={setSelectedId}
              filter={listFilter}
              onFilterChange={setListFilter}
            />
          )}
        </div>

        {/* 中央: 原本画像 */}
        <div className="overflow-hidden">
          {detailLoading ? (
            <div className="flex items-center justify-center h-full bg-slate-900 rounded-xl">
              <div className="animate-spin h-6 w-6 rounded-full border-2 border-blue-400 border-t-transparent" />
            </div>
          ) : detail ? (
            <OriginalImagePanel doc={detail} />
          ) : (
            <div className="bg-slate-900 rounded-xl flex items-center justify-center h-full text-slate-500">
              <div className="text-center">
                <p className="text-3xl mb-2">🖼️</p>
                <p className="text-sm">書類を選択すると画像が表示されます</p>
              </div>
            </div>
          )}
        </div>

        {/* 右: 抽出データ・編集 */}
        <div className="overflow-hidden">
          {detailLoading ? (
            <div className="flex items-center justify-center h-full bg-white rounded-xl border border-slate-200">
              <div className="animate-spin h-6 w-6 rounded-full border-2 border-blue-500 border-t-transparent" />
            </div>
          ) : detail ? (
            <ExtractionForm
              detail={detail}
              onSave={handleSave}
              onApprove={handleApprove}
              onReject={handleReject}
            />
          ) : (
            <div className="bg-white rounded-xl border border-slate-200 flex items-center justify-center h-full text-slate-400">
              <div className="text-center">
                <p className="text-4xl mb-2">👈</p>
                <p className="text-sm font-medium">左側の書類を選択</p>
                <p className="text-xs mt-1">OCR 抽出結果の確認・修正</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// useSearchParams() requires a Suspense boundary in Next.js App Router
export default function ReviewPage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center text-slate-400">読み込み中...</div>}>
      <ReviewPageInner />
    </Suspense>
  );
}
