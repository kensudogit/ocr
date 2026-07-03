"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { uploadApi } from "@/lib/api";

type UploadMode = "single" | "batch";

interface FileItem {
  file: File;
  status: "waiting" | "uploading" | "done" | "error";
  docId?: string;
  errorMsg?: string;
}

// ── ドロップゾーン ──────────────────────────────────────────────────
function DropZone({
  onFiles,
  multiple = false,
}: {
  onFiles: (files: File[]) => void;
  multiple?: boolean;
}) {
  const [dragging, setDragging] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const files = Array.from(e.dataTransfer.files).filter((f) => isAllowed(f));
      if (files.length) onFiles(files);
    },
    [onFiles]
  );

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []).filter((f) => isAllowed(f));
    if (files.length) onFiles(files);
    e.target.value = "";
  };

  return (
    <label
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={[
        "flex flex-col items-center justify-center w-full h-48 rounded-2xl border-2 border-dashed cursor-pointer transition-all",
        dragging
          ? "border-blue-400 bg-blue-50 scale-[1.01]"
          : "border-slate-300 bg-slate-50 hover:border-blue-300 hover:bg-blue-50",
      ].join(" ")}
    >
      <input
        type="file"
        accept=".jpg,.jpeg,.png,.pdf,.tiff,.tif,.bmp,.webp"
        multiple={multiple}
        className="sr-only"
        onChange={handleChange}
      />
      <span className="text-4xl mb-3">📁</span>
      <p className="font-semibold text-slate-700">
        ここにファイルをドロップ、またはクリックして選択
      </p>
      <p className="text-sm text-slate-400 mt-1">
        JPG / PNG / PDF / TIFF 対応 | 1ファイル最大 50MB
      </p>
    </label>
  );
}

function isAllowed(file: File): boolean {
  const allowed = ["image/jpeg", "image/png", "application/pdf", "image/tiff", "image/bmp", "image/webp"];
  return allowed.includes(file.type) || file.name.match(/\.(jpg|jpeg|png|pdf|tiff|tif|bmp|webp)$/i) !== null;
}

// ── 単一アップロード ──────────────────────────────────────────────────
function SingleUpload() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<"idle" | "uploading" | "done" | "error">("idle");
  const [message, setMessage] = useState("");
  const [docId, setDocId] = useState<string | null>(null);

  const handleUpload = async () => {
    if (!file) return;
    setStatus("uploading");
    setMessage("");
    try {
      const result = await uploadApi.upload(file, true);
      setDocId(result.document_id);
      setStatus("done");
      setMessage("OCR 処理が完了しました。確認画面で内容をご確認ください。");
    } catch (e: unknown) {
      setStatus("error");
      setMessage(e instanceof Error ? e.message : "アップロードに失敗しました");
    }
  };

  return (
    <div className="space-y-4">
      <DropZone onFiles={(files) => setFile(files[0])} />

      {file && (
        <div className="flex items-center gap-3 bg-white rounded-xl border border-slate-200 p-4">
          <span className="text-2xl">{file.type === "application/pdf" ? "📄" : "🖼️"}</span>
          <div className="flex-1 min-w-0">
            <p className="font-medium text-slate-800 truncate">{file.name}</p>
            <p className="text-xs text-slate-400">{(file.size / 1024).toFixed(1)} KB</p>
          </div>
          <button
            onClick={() => { setFile(null); setStatus("idle"); }}
            className="text-slate-400 hover:text-red-500 text-lg"
          >
            ✕
          </button>
        </div>
      )}

      {status === "done" && (
        <div className="rounded-xl bg-green-50 border border-green-200 p-4">
          <p className="text-green-700 font-medium">{message}</p>
          {docId && (
            <button
              onClick={() => router.push(`/review?id=${docId}`)}
              className="mt-2 text-sm text-green-600 hover:text-green-800 underline"
            >
              確認画面を開く →
            </button>
          )}
        </div>
      )}

      {status === "error" && (
        <div className="rounded-xl bg-red-50 border border-red-200 p-4">
          <p className="text-red-700 font-medium">{message}</p>
        </div>
      )}

      <button
        onClick={handleUpload}
        disabled={!file || status === "uploading"}
        className={[
          "w-full py-3 rounded-xl font-semibold text-white transition-all text-sm",
          !file || status === "uploading"
            ? "bg-slate-300 cursor-not-allowed"
            : "bg-blue-600 hover:bg-blue-700 active:scale-[0.99]",
        ].join(" ")}
      >
        {status === "uploading" ? (
          <span className="flex items-center justify-center gap-2">
            <span className="animate-spin h-4 w-4 rounded-full border-2 border-white border-t-transparent" />
            OCR 処理中...（10〜30秒）
          </span>
        ) : (
          "アップロードして OCR 処理"
        )}
      </button>
    </div>
  );
}

// ── 一括アップロード ─────────────────────────────────────────────────
function BatchUpload() {
  const [files, setFiles] = useState<FileItem[]>([]);
  const [jobName, setJobName] = useState("");
  const [batchJobId, setBatchJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState<number>(0);
  const [batchStatus, setBatchStatus] = useState<string>("idle");

  const handleAddFiles = (newFiles: File[]) => {
    setFiles((prev) => [
      ...prev,
      ...newFiles.map((f) => ({ file: f, status: "waiting" as const })),
    ]);
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleBatchUpload = async () => {
    if (!files.length) return;
    setBatchStatus("uploading");
    try {
      const result = await uploadApi.batchUpload(files.map((f) => f.file), jobName);
      setBatchJobId(result.batch_job_id);
      setBatchStatus("processing");

      // ポーリングで進捗確認
      const poll = async () => {
        if (!result.batch_job_id) return;
        const status = await uploadApi.batchStatus(result.batch_job_id);
        setProgress(status.progress_percent);
        if (status.status === "completed" || status.status === "failed") {
          setBatchStatus(status.status);
        } else {
          setTimeout(poll, 3000);
        }
      };
      setTimeout(poll, 2000);
    } catch (e: unknown) {
      setBatchStatus("error");
    }
  };

  return (
    <div className="space-y-4">
      <DropZone onFiles={handleAddFiles} multiple />

      {/* ジョブ名 */}
      <div>
        <label className="block text-sm font-medium text-slate-700 mb-1">
          バッチ名（任意）
        </label>
        <input
          type="text"
          value={jobName}
          onChange={(e) => setJobName(e.target.value)}
          placeholder="例: 2024年3月分 領収書"
          className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* ファイルリスト */}
      {files.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="px-4 py-2 bg-slate-50 border-b border-slate-200 flex justify-between">
            <span className="text-xs font-semibold text-slate-600 uppercase">
              {files.length} ファイル選択中
            </span>
            <button
              onClick={() => setFiles([])}
              className="text-xs text-red-500 hover:text-red-700"
            >
              すべて削除
            </button>
          </div>
          <div className="max-h-60 overflow-y-auto divide-y divide-slate-100">
            {files.map((item, idx) => (
              <div key={idx} className="flex items-center gap-3 px-4 py-2">
                <span className="text-lg">{item.file.type === "application/pdf" ? "📄" : "🖼️"}</span>
                <span className="flex-1 text-sm text-slate-700 truncate">{item.file.name}</span>
                <span className="text-xs text-slate-400">
                  {(item.file.size / 1024).toFixed(0)} KB
                </span>
                <button
                  onClick={() => removeFile(idx)}
                  className="text-slate-300 hover:text-red-500"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 進捗バー */}
      {batchStatus === "processing" && (
        <div className="space-y-2">
          <div className="flex justify-between text-sm text-slate-600">
            <span>処理中...</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-slate-200 rounded-full h-3">
            <div
              className="bg-blue-500 h-3 rounded-full transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {batchStatus === "completed" && (
        <div className="rounded-xl bg-green-50 border border-green-200 p-4">
          <p className="text-green-700 font-medium">✅ 一括処理が完了しました</p>
          <a href="/review?status=pending" className="text-sm text-green-600 underline mt-1 block">
            確認画面で結果を確認する →
          </a>
        </div>
      )}

      <button
        onClick={handleBatchUpload}
        disabled={!files.length || batchStatus === "uploading" || batchStatus === "processing"}
        className={[
          "w-full py-3 rounded-xl font-semibold text-white transition-all text-sm",
          !files.length || batchStatus === "uploading" || batchStatus === "processing"
            ? "bg-slate-300 cursor-not-allowed"
            : "bg-blue-600 hover:bg-blue-700",
        ].join(" ")}
      >
        {batchStatus === "uploading"
          ? "アップロード中..."
          : batchStatus === "processing"
          ? `OCR処理中 (${progress}%)`
          : `${files.length} 件を一括アップロード`}
      </button>
    </div>
  );
}

// ── メインページ ────────────────────────────────────────────────────
export default function UploadPage() {
  const [mode, setMode] = useState<UploadMode>("single");

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">書類アップロード</h1>
        <p className="text-sm text-slate-500 mt-1">
          領収書・請求書・カード明細をアップロードすると OCR が自動で内容を読み取ります
        </p>
      </div>

      {/* モード切替 */}
      <div className="flex rounded-xl border border-slate-200 p-1 bg-white">
        {([["single", "1件ずつ"], ["batch", "一括（複数ファイル）"]] as const).map(([m, label]) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={[
              "flex-1 py-2 rounded-lg text-sm font-medium transition-all",
              mode === m
                ? "bg-blue-600 text-white shadow-sm"
                : "text-slate-600 hover:text-slate-800",
            ].join(" ")}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ヒントカード */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
        <p className="text-sm font-semibold text-blue-800">対応書類</p>
        <ul className="text-xs text-blue-600 mt-1 space-y-0.5 list-disc list-inside">
          <li>感熱紙レシート（コンビニ・スーパー・ガソリンスタンド等）</li>
          <li>手書き領収書（氏名・金額・但し書き等を自動抽出）</li>
          <li>請求書 PDF（適格請求書番号・支払期日を抽出）</li>
          <li>クレジットカード明細（利用日・金額・取引先を抽出）</li>
        </ul>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200 p-6">
        {mode === "single" ? <SingleUpload /> : <BatchUpload />}
      </div>
    </div>
  );
}
