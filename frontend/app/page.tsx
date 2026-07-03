"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  documentsApi,
  formatCurrency,
  formatDate,
  DOC_TYPE_LABELS,
  STATUS_LABELS,
  STATUS_COLORS,
  type Stats,
  type Document,
} from "@/lib/api";

// ── KPI カード ──────────────────────────────────────────────────────
function KpiCard({
  label,
  value,
  sub,
  color = "blue",
}: {
  label: string;
  value: string | number;
  sub?: string;
  color?: "blue" | "green" | "yellow" | "purple";
}) {
  const colors = {
    blue:   "bg-blue-50 border-blue-200 text-blue-700",
    green:  "bg-green-50 border-green-200 text-green-700",
    yellow: "bg-yellow-50 border-yellow-200 text-yellow-700",
    purple: "bg-purple-50 border-purple-200 text-purple-700",
  };
  return (
    <div className={`rounded-xl border-2 p-5 ${colors[color]}`}>
      <p className="text-xs font-semibold uppercase tracking-wide opacity-70">{label}</p>
      <p className="text-3xl font-bold mt-1">{value}</p>
      {sub && <p className="text-xs mt-1 opacity-60">{sub}</p>}
    </div>
  );
}

// ── ドーナツ風の書類種別グラフ（シンプルなバー） ─────────────────────
function TypeBar({ types }: { types: Record<string, number> }) {
  const total = Object.values(types).reduce((s, v) => s + v, 0);
  const colors: Record<string, string> = {
    receipt:        "bg-blue-400",
    handwritten:    "bg-amber-400",
    invoice:        "bg-green-400",
    card_statement: "bg-purple-400",
    bank_statement: "bg-rose-400",
    unknown:        "bg-slate-300",
  };
  return (
    <div className="space-y-2">
      {Object.entries(types).map(([type, count]) => (
        <div key={type} className="flex items-center gap-3">
          <span className="text-sm text-slate-600 w-28 truncate">{DOC_TYPE_LABELS[type] ?? type}</span>
          <div className="flex-1 bg-slate-100 rounded-full h-3 overflow-hidden">
            <div
              className={`h-3 rounded-full ${colors[type] ?? "bg-slate-400"} transition-all`}
              style={{ width: `${total ? (count / total) * 100 : 0}%` }}
            />
          </div>
          <span className="text-sm font-medium text-slate-700 w-8 text-right">{count}</span>
        </div>
      ))}
    </div>
  );
}

// ── ステータス内訳 ──────────────────────────────────────────────────
function StatusBreakdown({ statuses }: { statuses: Record<string, number> }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
      {Object.entries(statuses).map(([status, count]) => (
        <div
          key={status}
          className={`rounded-lg px-3 py-2 text-center ${STATUS_COLORS[status] ?? "bg-slate-100 text-slate-700"}`}
        >
          <p className="text-2xl font-bold">{count}</p>
          <p className="text-xs font-medium">{STATUS_LABELS[status] ?? status}</p>
        </div>
      ))}
    </div>
  );
}

// ── 最近の書類テーブル ──────────────────────────────────────────────
function RecentDocumentsTable({ docs }: { docs: Document[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50 text-left text-slate-500 text-xs uppercase tracking-wide">
            <th className="px-4 py-3 font-semibold">ファイル名</th>
            <th className="px-4 py-3 font-semibold">種別</th>
            <th className="px-4 py-3 font-semibold">取引先</th>
            <th className="px-4 py-3 font-semibold">日付</th>
            <th className="px-4 py-3 font-semibold">金額</th>
            <th className="px-4 py-3 font-semibold">ステータス</th>
            <th className="px-4 py-3 font-semibold">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {docs.map((doc) => (
            <tr key={doc.id} className="hover:bg-slate-50 transition-colors">
              <td className="px-4 py-3">
                <span className="text-slate-800 font-medium truncate max-w-[200px] block">
                  {doc.original_filename}
                </span>
              </td>
              <td className="px-4 py-3 text-slate-600">
                {DOC_TYPE_LABELS[doc.doc_type] ?? doc.doc_type}
              </td>
              <td className="px-4 py-3 text-slate-600 truncate max-w-[150px]">
                {doc.vendor_name ?? "—"}
              </td>
              <td className="px-4 py-3 text-slate-600">{formatDate(doc.transaction_date)}</td>
              <td className="px-4 py-3 font-medium text-slate-800">
                {formatCurrency(doc.total_amount)}
              </td>
              <td className="px-4 py-3">
                <span
                  className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[doc.status] ?? "bg-slate-100 text-slate-700"}`}
                >
                  {STATUS_LABELS[doc.status] ?? doc.status}
                </span>
              </td>
              <td className="px-4 py-3">
                <Link
                  href={`/review?id=${doc.id}`}
                  className="text-blue-600 hover:text-blue-800 text-xs font-medium hover:underline"
                >
                  確認
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── メインページ ────────────────────────────────────────────────────
export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [recentDocs, setRecentDocs] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([documentsApi.stats(), documentsApi.list({ page_size: 10 })])
      .then(([statsData, listData]) => {
        setStats(statsData);
        setRecentDocs(listData.items);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-10 w-10 border-4 border-blue-500 border-t-transparent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl bg-red-50 border border-red-200 p-6 text-center">
        <p className="text-red-600 font-medium">バックエンドに接続できません</p>
        <p className="text-sm text-red-500 mt-1">{error}</p>
        <p className="text-xs text-slate-500 mt-3">
          バックエンドサーバーを起動してください: <code>uvicorn src.main:app --reload</code>
        </p>
      </div>
    );
  }

  const pendingCount = stats?.status_breakdown?.pending ?? 0;
  const approvedCount = stats?.status_breakdown?.approved ?? 0;
  const totalDocs = Object.values(stats?.status_breakdown ?? {}).reduce((s, v) => s + v, 0);

  return (
    <div className="space-y-6">
      {/* ページヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">ダッシュボード</h1>
          <p className="text-sm text-slate-500 mt-1">書類OCR処理の概要</p>
        </div>
        <Link
          href="/upload"
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
        >
          <span>＋</span>
          書類をアップロード
        </Link>
      </div>

      {/* KPI カード */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="今月の処理数"
          value={stats?.monthly_upload_count ?? 0}
          sub="枚（今月アップロード）"
          color="blue"
        />
        <KpiCard
          label="確認待ち"
          value={pendingCount}
          sub="件 → 確認・修正が必要"
          color="yellow"
        />
        <KpiCard
          label="承認済み"
          value={approvedCount}
          sub="件 → エクスポート可能"
          color="green"
        />
        <KpiCard
          label="承認済み合計金額"
          value={formatCurrency(stats?.total_approved_amount ?? 0)}
          sub="承認済み書類の合計"
          color="purple"
        />
      </div>

      {/* 確認待ちのアラート */}
      {pendingCount > 0 && (
        <div className="rounded-xl bg-yellow-50 border border-yellow-200 p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-yellow-500 text-xl">⚠️</span>
            <div>
              <p className="font-medium text-yellow-800">
                {pendingCount} 件の書類が確認待ちです
              </p>
              <p className="text-sm text-yellow-600">
                OCR 抽出結果を確認・修正して承認してください
              </p>
            </div>
          </div>
          <Link
            href="/review?status=pending"
            className="bg-yellow-500 hover:bg-yellow-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            確認する
          </Link>
        </div>
      )}

      {/* 2カラムグリッド */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 書類種別内訳 */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-base font-semibold text-slate-800 mb-4">書類種別内訳</h2>
          {Object.keys(stats?.doc_type_breakdown ?? {}).length === 0 ? (
            <p className="text-slate-400 text-sm text-center py-8">書類がありません</p>
          ) : (
            <TypeBar types={stats?.doc_type_breakdown ?? {}} />
          )}
        </div>

        {/* ステータス内訳 */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-base font-semibold text-slate-800 mb-4">処理ステータス</h2>
          {Object.keys(stats?.status_breakdown ?? {}).length === 0 ? (
            <p className="text-slate-400 text-sm text-center py-8">書類がありません</p>
          ) : (
            <StatusBreakdown statuses={stats?.status_breakdown ?? {}} />
          )}
        </div>
      </div>

      {/* 最近の書類 */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-slate-800">最近の書類</h2>
          <Link
            href="/review"
            className="text-sm text-blue-600 hover:text-blue-800 font-medium"
          >
            すべて見る →
          </Link>
        </div>
        {recentDocs.length === 0 ? (
          <div className="text-center py-12 text-slate-400">
            <p className="text-4xl mb-3">📭</p>
            <p className="font-medium">書類がありません</p>
            <p className="text-sm mt-1">
              <Link href="/upload" className="text-blue-600 hover:underline">
                書類をアップロード
              </Link>
              して OCR 処理を開始してください
            </p>
          </div>
        ) : (
          <RecentDocumentsTable docs={recentDocs} />
        )}
      </div>

      {/* クイックガイド */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <h2 className="text-base font-semibold text-slate-800 mb-4">処理フロー</h2>
        <div className="flex flex-wrap gap-4">
          {[
            { step: "1", title: "アップロード", desc: "レシート・請求書の画像またはPDFをアップロード", href: "/upload" },
            { step: "2", title: "OCR 自動処理", desc: "PaddleOCR が日付・金額・取引先を自動抽出", href: "/review" },
            { step: "3", title: "確認・修正", desc: "担当者が抽出結果を確認し、必要に応じて修正・承認", href: "/review" },
            { step: "4", title: "エクスポート", desc: "freee / マネーフォワード / 弥生会計 へCSV出力", href: "/export" },
          ].map((item) => (
            <Link
              key={item.step}
              href={item.href}
              className="flex-1 min-w-[200px] group p-4 rounded-xl border-2 border-slate-100 hover:border-blue-200 hover:bg-blue-50 transition-all"
            >
              <div className="flex items-start gap-3">
                <span className="flex-shrink-0 w-7 h-7 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm font-bold">
                  {item.step}
                </span>
                <div>
                  <p className="font-semibold text-slate-800 group-hover:text-blue-700">{item.title}</p>
                  <p className="text-xs text-slate-500 mt-0.5">{item.desc}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
