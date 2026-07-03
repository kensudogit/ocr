"use client";

import { useEffect, useState } from "react";
import {
  documentsApi,
  exportApi,
  formatCurrency,
  formatDate,
  DOC_TYPE_LABELS,
  type Document,
} from "@/lib/api";

const FORMAT_INFO = {
  freee: {
    name: "freee会計",
    logo: "🟠",
    desc: "freee会計 仕訳インポートCSV（UTF-8 BOM）",
    color: "border-orange-200 bg-orange-50",
    activeColor: "border-orange-400 bg-orange-100",
  },
  money_forward: {
    name: "マネーフォワード",
    logo: "🔵",
    desc: "マネーフォワード クラウド会計 仕訳帳CSV（UTF-8 BOM）",
    color: "border-blue-200 bg-blue-50",
    activeColor: "border-blue-400 bg-blue-100",
  },
  yayoi: {
    name: "弥生会計",
    logo: "🟢",
    desc: "弥生会計 仕訳日記帳CSVインポート（Shift-JIS）",
    color: "border-green-200 bg-green-50",
    activeColor: "border-green-400 bg-green-100",
  },
  generic_csv: {
    name: "汎用CSV",
    logo: "📊",
    desc: "全フィールドを含む汎用CSVファイル（UTF-8 BOM）",
    color: "border-slate-200 bg-slate-50",
    activeColor: "border-slate-400 bg-slate-100",
  },
} as const;

type FormatKey = keyof typeof FORMAT_INFO;

export default function ExportPage() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectedFormat, setSelectedFormat] = useState<FormatKey>("freee");
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    documentsApi
      .list({ status: "approved", page_size: 200 })
      .then((res) => {
        setDocs(res.items);
        setSelectedIds(new Set(res.items.map((d) => d.id)));
      })
      .finally(() => setLoading(false));
  }, []);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => setSelectedIds(new Set(docs.map((d) => d.id)));
  const clearAll = () => setSelectedIds(new Set());

  const handleExport = async () => {
    if (!selectedIds.size) return;
    setExporting(true);
    setMessage(null);
    try {
      const filename = await exportApi.export(selectedFormat, Array.from(selectedIds));
      setMessage({ type: "success", text: `✅ ${filename} をダウンロードしました` });
    } catch (e: unknown) {
      setMessage({
        type: "error",
        text: e instanceof Error ? e.message : "エクスポートに失敗しました",
      });
    } finally {
      setExporting(false);
    }
  };

  const totalSelected = selectedIds.size;
  const totalAmount = docs
    .filter((d) => selectedIds.has(d.id))
    .reduce((s, d) => s + (d.total_amount ?? 0), 0);

  return (
    <div className="space-y-6">
      {/* ヘッダー */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">エクスポート</h1>
        <p className="text-sm text-slate-500 mt-1">
          承認済み書類を会計ソフト用CSVファイルでエクスポートします
        </p>
      </div>

      {/* フォーマット選択 */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <h2 className="font-semibold text-slate-800 mb-4">1. エクスポート先を選択</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {(Object.entries(FORMAT_INFO) as [FormatKey, typeof FORMAT_INFO[FormatKey]][]).map(
            ([key, info]) => (
              <button
                key={key}
                onClick={() => setSelectedFormat(key)}
                className={[
                  "text-left p-4 rounded-xl border-2 transition-all",
                  selectedFormat === key ? info.activeColor : info.color,
                  "hover:shadow-sm",
                ].join(" ")}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-2xl">{info.logo}</span>
                  {selectedFormat === key && (
                    <span className="text-xs bg-white px-1.5 py-0.5 rounded-full font-semibold text-slate-600 border border-slate-300">
                      選択中
                    </span>
                  )}
                </div>
                <p className="font-semibold text-slate-800 text-sm">{info.name}</p>
                <p className="text-xs text-slate-500 mt-0.5">{info.desc}</p>
              </button>
            )
          )}
        </div>
      </div>

      {/* 書類選択 */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-slate-800">2. エクスポート対象を選択</h2>
          <div className="flex items-center gap-2 text-xs">
            <button onClick={selectAll} className="text-blue-600 hover:underline">すべて選択</button>
            <span className="text-slate-300">|</span>
            <button onClick={clearAll} className="text-slate-500 hover:underline">すべて解除</button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-24">
            <div className="animate-spin h-6 w-6 rounded-full border-2 border-blue-500 border-t-transparent" />
          </div>
        ) : docs.length === 0 ? (
          <div className="text-center py-8 text-slate-400">
            <p className="text-3xl mb-2">📭</p>
            <p className="font-medium">承認済みの書類がありません</p>
            <a href="/review" className="text-sm text-blue-600 hover:underline mt-1 block">
              確認・承認画面へ →
            </a>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-left text-xs text-slate-500 uppercase tracking-wide">
                  <th className="px-4 py-3 w-10">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === docs.length}
                      onChange={() => selectedIds.size === docs.length ? clearAll() : selectAll()}
                      className="rounded"
                    />
                  </th>
                  <th className="px-4 py-3 font-semibold">ファイル名</th>
                  <th className="px-4 py-3 font-semibold">種別</th>
                  <th className="px-4 py-3 font-semibold">取引先</th>
                  <th className="px-4 py-3 font-semibold">取引日</th>
                  <th className="px-4 py-3 font-semibold text-right">金額</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {docs.map((doc) => (
                  <tr
                    key={doc.id}
                    className={`transition-colors cursor-pointer ${
                      selectedIds.has(doc.id) ? "bg-blue-50" : "hover:bg-slate-50"
                    }`}
                    onClick={() => toggleSelect(doc.id)}
                  >
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(doc.id)}
                        onChange={() => toggleSelect(doc.id)}
                        onClick={(e) => e.stopPropagation()}
                        className="rounded"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-slate-800 font-medium truncate max-w-[180px] block">
                        {doc.original_filename}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600 text-xs">
                      {DOC_TYPE_LABELS[doc.doc_type] ?? doc.doc_type}
                    </td>
                    <td className="px-4 py-3 text-slate-600 truncate max-w-[150px]">
                      {doc.vendor_name ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{formatDate(doc.transaction_date)}</td>
                    <td className="px-4 py-3 font-medium text-slate-800 text-right">
                      {formatCurrency(doc.total_amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* エクスポート実行 */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <h2 className="font-semibold text-slate-800 mb-4">3. エクスポート実行</h2>

        {/* 選択サマリー */}
        <div className="flex items-center gap-6 mb-4 bg-slate-50 rounded-xl p-4">
          <div>
            <p className="text-xs text-slate-500">選択件数</p>
            <p className="text-2xl font-bold text-slate-800">{totalSelected} 件</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">合計金額</p>
            <p className="text-2xl font-bold text-slate-800">{formatCurrency(totalAmount)}</p>
          </div>
          <div className="ml-auto">
            <p className="text-xs text-slate-500">出力形式</p>
            <p className="font-semibold text-slate-700">
              {FORMAT_INFO[selectedFormat].logo} {FORMAT_INFO[selectedFormat].name}
            </p>
          </div>
        </div>

        {message && (
          <div className={`rounded-xl p-3 text-sm font-medium mb-4 ${
            message.type === "success" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
          }`}>
            {message.text}
          </div>
        )}

        <button
          onClick={handleExport}
          disabled={!totalSelected || exporting}
          className={[
            "w-full py-3 rounded-xl font-semibold text-white transition-all text-sm",
            !totalSelected || exporting
              ? "bg-slate-300 cursor-not-allowed"
              : "bg-blue-600 hover:bg-blue-700 active:scale-[0.99]",
          ].join(" ")}
        >
          {exporting ? (
            <span className="flex items-center justify-center gap-2">
              <span className="animate-spin h-4 w-4 rounded-full border-2 border-white border-t-transparent" />
              エクスポート中...
            </span>
          ) : (
            `${totalSelected} 件を ${FORMAT_INFO[selectedFormat].name} 形式でエクスポート`
          )}
        </button>

        <p className="text-xs text-slate-400 mt-2 text-center">
          ※ エクスポート後、書類のステータスが「エクスポート済み」に変更されます
        </p>
      </div>
    </div>
  );
}
