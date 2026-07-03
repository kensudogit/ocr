"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/",             label: "ダッシュボード" },
  { href: "/upload",       label: "アップロード" },
  { href: "/review",       label: "確認・修正" },
  { href: "/export",       label: "エクスポート" },
  { href: "/test-results", label: "テスト結果" },
];

export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-50 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center h-14 gap-8">
          {/* ロゴ */}
          <Link href="/" className="flex items-center gap-2 font-bold text-blue-600 text-lg shrink-0">
            <span className="text-xl">📄</span>
            <span>OCR仕訳システム</span>
          </Link>

          {/* ナビリンク */}
          <nav className="flex items-center gap-1">
            {NAV_LINKS.map((link) => {
              const active =
                link.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={[
                    "px-4 py-2 rounded-md text-sm font-medium transition-colors",
                    active
                      ? "bg-blue-50 text-blue-700"
                      : "text-slate-600 hover:text-slate-900 hover:bg-slate-100",
                  ].join(" ")}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-slate-400 bg-slate-100 px-2 py-1 rounded">
              税理士事務所専用
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
