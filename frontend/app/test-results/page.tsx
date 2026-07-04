"use client";

/**
 * テスト結果確認ページ
 *
 * バックエンドの /test-report API からテスト結果を取得し、
 * カバレッジ・合格率・失敗一覧を表示する。
 * pytest-html レポートと coverage レポートを iframe で埋め込む。
 */

import { useState, useEffect, useCallback, useRef } from "react";

// ── 型定義 ──────────────────────────────────────────────────────────────

interface TestSummary {
  total: number;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  pass_rate: number;
  time_seconds: number;
  failed_cases: Array<{
    name: string;
    classname: string;
    message: string;
  }>;
}

interface TestRunState {
  status: "idle" | "running" | "completed" | "failed";
  started_at: string | null;
  completed_at: string | null;
  exit_code: number | null;
  summary: TestSummary | null;
}

interface TestReportData {
  status: string;
  run_state: TestRunState;
  summary: TestSummary | null;
  report_html_url: string;
  coverage_url: string;
  last_updated: number | null;
  html_report_exists?: boolean;
  message?: string;
}

/** API から返った summary がエラー dict でないか検証する */
function isValidSummary(s: unknown): s is TestSummary {
  if (!s || typeof s !== "object") return false;
  const o = s as Record<string, unknown>;
  return typeof o.total === "number" && typeof o.pass_rate === "number";
}

// ── ユーティリティ ────────────────────────────────────────────────────

// In production (Railway) NEXT_PUBLIC_API_URL is not set; default to /api
// so all requests go through the Next.js server-side proxy (no CORS issues).
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

async function fetchTestReport(): Promise<TestReportData> {
  const res = await fetch(`${API_BASE}/test-report`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function runTests(markers = "", testPath = "tests"): Promise<{ message: string }> {
  const params = new URLSearchParams({ markers, test_path: testPath });
  const res = await fetch(`${API_BASE}/test-report/run?${params}`, { method: "POST" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function formatTime(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}秒`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}分${s}秒`;
}

// ── UI コンポーネント ─────────────────────────────────────────────────

function StatCard({
  value,
  label,
  color,
}: {
  value: string | number;
  label: string;
  color: string;
}) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
      <p className={`text-3xl font-bold ${color}`}>{value}</p>
      <p className="text-sm text-gray-500 mt-1">{label}</p>
    </div>
  );
}

function PassRateBar({ rate }: { rate: number }) {
  const color =
    rate >= 90 ? "bg-green-500" : rate >= 70 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="w-full bg-gray-100 rounded-full h-3">
      <div
        className={`${color} h-3 rounded-full transition-all duration-700`}
        style={{ width: `${rate}%` }}
      />
    </div>
  );
}

function MarkerFilter({
  selected,
  onChange,
}: {
  selected: string;
  onChange: (v: string) => void;
}) {
  const markers = [
    { value: "", label: "全テスト" },
    { value: "unit", label: "Unit のみ" },
    { value: "integration", label: "Integration のみ" },
    { value: "invoice", label: "インボイス検証" },
    { value: "pii", label: "PII マスク" },
    { value: "electronic_bookkeeping", label: "電帳法" },
    { value: "not slow", label: "高速のみ" },
  ];

  return (
    <div className="flex flex-wrap gap-2">
      {markers.map((m) => (
        <button
          key={m.value}
          onClick={() => onChange(m.value)}
          className={`px-3 py-1 rounded-full text-sm border transition-colors ${
            selected === m.value
              ? "bg-indigo-600 text-white border-indigo-600"
              : "bg-white text-gray-600 border-gray-300 hover:border-indigo-400"
          }`}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}

function FailedCasesList({
  cases,
}: {
  cases: TestSummary["failed_cases"];
}) {
  if (!cases || cases.length === 0) return null;
  return (
    <div className="space-y-2">
      {cases.map((c, i) => (
        <div key={i} className="bg-red-50 border border-red-200 rounded-lg p-3">
          <p className="text-sm font-semibold text-red-800 font-mono">
            {c.classname}::{c.name}
          </p>
          {c.message && (
            <p className="text-xs text-red-600 mt-1 font-mono whitespace-pre-wrap">
              {c.message}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

// ── メインページ ─────────────────────────────────────────────────────

export default function TestResultsPage() {
  const [data, setData] = useState<TestReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [selectedMarker, setSelectedMarker] = useState("");
  const [activeTab, setActiveTab] = useState<"summary" | "report" | "coverage">("summary");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [reportSrcdoc, setReportSrcdoc] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [coverageSrcdoc, setCoverageSrcdoc] = useState<string | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const result = await fetchTestReport();
      setData(result);
      setRunning(result.run_state?.status === "running");
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // テスト実行中は 3 秒ごとに自動更新
  useEffect(() => {
    if (!running && !autoRefresh) return;
    const interval = setInterval(() => {
      loadData();
    }, 3000);
    return () => clearInterval(interval);
  }, [running, autoRefresh, loadData]);

  // HTML レポートをタブ選択時に fetch して srcdoc に設定する
  useEffect(() => {
    if (activeTab === "report" && reportSrcdoc === null && !reportLoading) {
      setReportLoading(true);
      fetch(`${API_BASE}/test-report/html`)
        .then((r) => r.text())
        .then((html) => setReportSrcdoc(html))
        .catch(() => setReportSrcdoc("<p style='padding:20px'>レポートを読み込めませんでした。まずテストを実行してください。</p>"))
        .finally(() => setReportLoading(false));
    }
    if (activeTab === "coverage" && coverageSrcdoc === null && !coverageLoading) {
      setCoverageLoading(true);
      fetch(`${API_BASE}/test-report/coverage`)
        .then((r) => r.text())
        .then((html) => setCoverageSrcdoc(html))
        .catch(() => setCoverageSrcdoc("<p style='padding:20px'>カバレッジレポートを読み込めませんでした。</p>"))
        .finally(() => setCoverageLoading(false));
    }
  }, [activeTab, reportSrcdoc, reportLoading, coverageSrcdoc, coverageLoading]);

  // テスト完了後に srcdoc をリセットして最新レポートを再取得させる
  useEffect(() => {
    const prevStatus = running;
    if (!prevStatus) return;
    if (!running) {
      setReportSrcdoc(null);
      setCoverageSrcdoc(null);
    }
  }, [running]);

  const handleRunTests = async () => {
    setRunning(true);
    setFeedback(null);
    try {
      const result = await runTests(selectedMarker);
      setFeedback(result.message);
      setAutoRefresh(true);
      // 新規実行なのでキャッシュ済みのレポートをクリア
      setReportSrcdoc(null);
      setCoverageSrcdoc(null);
      setTimeout(loadData, 1000);
    } catch (err) {
      setFeedback(`エラー: ${err}`);
      setRunning(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-500">読み込み中...</p>
      </div>
    );
  }

  // エラー dict（{error:...} や {parse_error:...}）を除外してから使用する
  const rawSummary = data?.summary ?? data?.run_state?.summary;
  const summary = isValidSummary(rawSummary) ? rawSummary : null;
  const runState = data?.run_state;

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-6xl mx-auto px-4 py-8 space-y-6">
        {/* ── ヘッダ ────────────────────────────────────────────── */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">テスト結果</h1>
            <p className="text-sm text-gray-500 mt-1">
              税理士事務所向け AI-OCR システム — 自動テストスイート
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded"
              />
              自動更新 (3秒)
            </label>
            <button
              onClick={loadData}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50"
            >
              更新
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">
            バックエンドに接続できません: {error}
            <br />
            <span className="text-xs">バックエンドが起動していることを確認してください（PORT 8000）</span>
          </div>
        )}

        {/* ── テスト実行コントロール ─────────────────────────────── */}
        <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
          <h2 className="text-base font-semibold text-gray-800">テスト実行</h2>
          <MarkerFilter selected={selectedMarker} onChange={setSelectedMarker} />
          <div className="flex items-center gap-3">
            <button
              onClick={handleRunTests}
              disabled={running}
              className="px-5 py-2.5 bg-indigo-600 text-white rounded-lg font-medium text-sm hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {running ? (
                <span className="flex items-center gap-2">
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z" />
                  </svg>
                  テスト実行中...
                </span>
              ) : (
                "テストを実行する"
              )}
            </button>
            {running && (
              <span className="text-sm text-gray-500">
                開始: {runState?.started_at ? new Date(runState.started_at).toLocaleTimeString() : "—"}
              </span>
            )}
            {feedback && (
              <span className="text-sm text-indigo-600">{feedback}</span>
            )}
          </div>
        </div>

        {/* ── サマリーカード ─────────────────────────────────────── */}
        {summary && (
          <div className="space-y-4">
            <Grid summary={summary} runState={runState} />
          </div>
        )}

        {/* ── タブ ────────────────────────────────────────────────── */}
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <div className="flex border-b border-gray-200">
            {(["summary", "report", "coverage"] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`flex-1 py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === tab
                    ? "border-indigo-600 text-indigo-600"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                {tab === "summary" ? "テスト詳細" : tab === "report" ? "HTML レポート" : "カバレッジ"}
              </button>
            ))}
          </div>

          <div className="p-5">
            {/* サマリータブ */}
            {activeTab === "summary" && (
              <div className="space-y-5">
                {!summary ? (
                  <p className="text-gray-500 text-sm">
                    テストを実行するとここに結果が表示されます。
                  </p>
                ) : (
                  <>
                    <div>
                      <div className="flex justify-between text-sm text-gray-600 mb-1">
                        <span>合格率</span>
                        <span className="font-semibold">{summary.pass_rate}%</span>
                      </div>
                      <PassRateBar rate={summary.pass_rate} />
                    </div>
                    {summary.failed_cases && summary.failed_cases.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-red-700 mb-2">
                          失敗したテスト ({summary.failed + summary.errors} 件)
                        </h3>
                        <FailedCasesList cases={summary.failed_cases} />
                      </div>
                    )}
                    {summary.failed === 0 && summary.errors === 0 && (
                      <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-green-800 text-sm">
                        全てのテストが合格しました！
                        実行時間: {formatTime(summary.time_seconds)}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {/* HTML レポートタブ */}
            {activeTab === "report" && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <a
                    href={`${API_BASE}/test-report/html`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-3 py-1.5 text-sm bg-indigo-50 text-indigo-700 border border-indigo-200 rounded hover:bg-indigo-100"
                  >
                    別タブで開く
                  </a>
                  {reportLoading && (
                    <span className="text-xs text-gray-400">読み込み中...</span>
                  )}
                </div>
                {reportSrcdoc ? (
                  <iframe
                    srcDoc={reportSrcdoc}
                    sandbox="allow-scripts allow-same-origin"
                    className="w-full h-[600px] border border-gray-200 rounded bg-white"
                    title="pytest HTML レポート"
                  />
                ) : reportLoading ? (
                  <div className="w-full h-[200px] flex items-center justify-center text-gray-400 border border-gray-200 rounded">
                    レポートを読み込んでいます...
                  </div>
                ) : (
                  <div className="w-full h-[200px] flex items-center justify-center text-gray-400 border border-gray-200 rounded text-sm">
                    テストを実行するとここにHTMLレポートが表示されます
                  </div>
                )}
              </div>
            )}

            {/* カバレッジタブ */}
            {activeTab === "coverage" && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <a
                    href={`${API_BASE}/test-report/coverage`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-3 py-1.5 text-sm bg-indigo-50 text-indigo-700 border border-indigo-200 rounded hover:bg-indigo-100"
                  >
                    別タブで開く
                  </a>
                  {coverageLoading && (
                    <span className="text-xs text-gray-400">読み込み中...</span>
                  )}
                </div>
                {coverageSrcdoc ? (
                  <iframe
                    srcDoc={coverageSrcdoc}
                    sandbox="allow-scripts allow-same-origin"
                    className="w-full h-[600px] border border-gray-200 rounded bg-white"
                    title="カバレッジレポート"
                  />
                ) : coverageLoading ? (
                  <div className="w-full h-[200px] flex items-center justify-center text-gray-400 border border-gray-200 rounded">
                    カバレッジレポートを読み込んでいます...
                  </div>
                ) : (
                  <div className="w-full h-[200px] flex items-center justify-center text-gray-400 border border-gray-200 rounded text-sm">
                    テストを実行するとここにカバレッジレポートが表示されます
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* ── テスト一覧 ───────────────────────────────────────────── */}
        <TestModuleList failedCases={summary?.failed_cases} />
      </div>
    </div>
  );
}

// ── サマリーグリッド ──────────────────────────────────────────────────

function Grid({
  summary,
  runState,
}: {
  summary: TestSummary;
  runState: TestRunState | undefined;
}) {
  const failCount = (summary.failed ?? 0) + (summary.errors ?? 0);
  const passRate  = summary.pass_rate ?? 0;
  const statusColor = failCount > 0 ? "text-red-600" : "text-green-600";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard value={summary.total   ?? 0} label="総テスト数" color="text-gray-800" />
        <StatCard value={summary.passed  ?? 0} label="合格"       color="text-green-600" />
        <StatCard value={failCount}             label="失敗"       color="text-red-600" />
        <StatCard value={summary.skipped ?? 0} label="スキップ"   color="text-yellow-600" />
        <StatCard value={`${passRate}%`}        label="合格率"     color={statusColor} />
      </div>
      <div className="flex flex-wrap gap-4 text-sm text-gray-500">
        <span>実行時間: {summary.time_seconds ?? 0}秒</span>
        {runState?.completed_at && (
          <span>
            最終実行: {new Date(runState.completed_at).toLocaleString("ja-JP")}
          </span>
        )}
        {runState != null && runState.exit_code !== null && (
          <span
            className={runState.exit_code === 0 ? "text-green-600" : "text-red-600"}
          >
            終了コード: {runState.exit_code}
          </span>
        )}
      </div>
    </div>
  );
}

// ── テストモジュール一覧 ─────────────────────────────────────────────

const MODULE_DEFS = [
  { file: "tests/core/test_invoice_validator.py", name: "インボイス番号検証",   markers: ["unit","invoice"],                count: 19, desc: "T+13桁 形式検証・チェックデジット・OCR 誤認識吸収" },
  { file: "tests/core/test_pii_masker.py",         name: "PII マスク",           markers: ["unit","pii"],                    count: 17, desc: "マイナンバー・口座番号・カード番号 マスク/復元・Luhn 検証" },
  { file: "tests/core/test_confidence_scorer.py",  name: "信頼度スコアリング",   markers: ["unit"],                          count: 14, desc: "3段階分類・検算ロジック・スコア計算・境界値" },
  { file: "tests/core/test_rule_engine.py",        name: "ルールエンジン",       markers: ["unit"],                          count: 17, desc: "キーワードマッピング・過去仕訳学習・顧問先別分離" },
  { file: "tests/core/test_classifier.py",         name: "書類分類",             markers: ["unit"],                          count: 14, desc: "レシート・手書き・請求書・カード明細 の分類" },
  { file: "tests/core/test_journal_model.py",      name: "仕訳データモデル",     markers: ["unit"],                          count: 20, desc: "freee/MF/弥生 アダプタ・顧問先マスタ・名寄せ" },
  { file: "tests/core/test_electronic_bookkeeping.py", name: "電子帳簿保存法",  markers: ["unit","electronic_bookkeeping"], count: 14, desc: "解像度チェック・SHA-256 ハッシュ・原本保存・改ざん検知" },
  { file: "tests/core/test_extractor.py",          name: "データ抽出",           markers: ["unit"],                          count: 22, desc: "日付・金額・取引先・インボイス番号・支払方法 抽出" },
  { file: "tests/core/test_audit_log.py",          name: "監査ログ",             markers: ["unit","security"],               count: 11, desc: "操作ログ・変更差分・セキュリティヘッダ" },
  { file: "tests/api/test_health.py",              name: "ヘルスチェック API",   markers: ["integration"],                   count:  7, desc: "FastAPI 起動・/health・/docs エンドポイント" },
  { file: "tests/api/test_upload_api.py",          name: "アップロード API",     markers: ["integration"],                   count:  9, desc: "ファイルアップロード・拡張子バリデーション・バッチ処理" },
  { file: "tests/api/test_documents_api.py",       name: "書類管理 API",         markers: ["integration"],                   count: 10, desc: "一覧・詳細・承認・差し戻し・統計" },
  { file: "tests/api/test_clients_api.py",         name: "顧問先管理 API",       markers: ["integration"],                   count:  8, desc: "顧問先 CRUD・統計・仕訳履歴" },
];

function TestModuleList({ failedCases }: { failedCases?: TestSummary["failed_cases"] }) {
  // テスト実行後は失敗クラス名からモジュール別状態を算出
  const failedClassnames = new Set(failedCases?.map((c) => c.classname) ?? []);

  const getModuleStatus = (file: string) => {
    if (!failedCases) return "unknown";          // 未実行
    const key = file.replace("tests/", "").replace(".py", "").replace(/\//g, ".");
    const hasFail = [...failedClassnames].some((cn) => cn.includes(key.split(".").at(-1) ?? ""));
    return hasFail ? "fail" : "pass";
  };

  const totalTests = MODULE_DEFS.reduce((s, m) => s + m.count, 0);

  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-800">テストモジュール一覧</h2>
        <span className="text-sm text-gray-500">合計 {totalTests} ケース</span>
      </div>
      <div className="divide-y divide-gray-100">
        {MODULE_DEFS.map((m) => {
          const status = getModuleStatus(m.file);
          return (
            <div key={m.file} className="px-5 py-3 hover:bg-gray-50 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    {status === "pass" && <span className="text-green-500 text-sm">✓</span>}
                    {status === "fail" && <span className="text-red-500 text-sm">✗</span>}
                    {status === "unknown" && <span className="text-gray-300 text-sm">○</span>}
                    <span className="text-sm font-medium text-gray-800">{m.name}</span>
                    {m.markers.map((tag) => (
                      <span key={tag} className="px-1.5 py-0.5 text-xs bg-gray-100 text-gray-500 rounded font-mono">
                        {tag}
                      </span>
                    ))}
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5 font-mono truncate">{m.file}</p>
                  <p className="text-xs text-gray-500 mt-1">{m.desc}</p>
                </div>
                <span className="text-sm font-semibold text-gray-700 whitespace-nowrap">
                  {m.count} ケース
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
