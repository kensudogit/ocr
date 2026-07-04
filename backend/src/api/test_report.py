"""テストレポート配信 API。

テスト実行後に生成される HTML レポートと
カバレッジレポートをブラウザから直接閲覧できるエンドポイント。

エンドポイント:
  GET /test-report/              テスト結果サマリー（JSON）
  GET /test-report/html          pytest-html レポートを HTML で配信
  GET /test-report/coverage      カバレッジレポートのトップページ
  POST /test-report/run          テストをバックグラウンドで実行
  GET /test-report/status        最後のテスト実行ステータス
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/test-report", tags=["test-report"])

# レポートファイルのパス
_BACKEND_DIR = Path(__file__).parent.parent.parent
_REPORT_HTML = _BACKEND_DIR / "test-reports" / "report.html"
_COVERAGE_DIR = _BACKEND_DIR / "test-reports" / "coverage"
_COVERAGE_HTML = _COVERAGE_DIR / "index.html"
_JUNIT_XML = _BACKEND_DIR / "test-reports" / "junit.xml"

# テスト実行状態（シングルトン）
_test_run_state: dict = {
    "status": "idle",     # idle / running / completed / failed
    "started_at": None,
    "completed_at": None,
    "exit_code": None,
    "summary": None,
}


@router.get("", summary="テスト結果サマリー（末尾スラッシュなし）")
@router.get("/", summary="テスト結果サマリー（JSON）")
async def get_test_summary():
    """最後のテスト実行結果のサマリーを JSON で返す。

    JUnit XML を解析してテスト件数・合格・失敗・スキップを集計する。
    """
    if not _JUNIT_XML.exists():
        return {
            "status": "no_results",
            "message": "テスト未実行です。POST /test-report/run でテストを実行してください。",
            "report_html_url": "/test-report/html",
            "run_url": "/test-report/run",
        }

    try:
        summary = _parse_junit_xml(_JUNIT_XML)
    except Exception as exc:
        logger.warning("JUnit XML 解析エラー: %s", exc)
        summary = _empty_summary()

    # run_state.summary も最新に同期
    if _test_run_state.get("summary") is None:
        _test_run_state["summary"] = summary

    return {
        "status": "available",
        "run_state": _test_run_state,
        "summary": summary,
        "report_html_url": "/test-report/html",
        "coverage_url": "/test-report/coverage",
        "junit_url": "/test-report/junit.xml",
        "last_updated": _REPORT_HTML.stat().st_mtime if _REPORT_HTML.exists() else None,
        "html_report_exists": _REPORT_HTML.exists(),
    }


@router.get("/html", summary="pytest-html レポートを表示")
async def get_html_report():
    """pytest-html で生成した HTML レポートを配信する。"""
    if not _REPORT_HTML.exists():
        return HTMLResponse(
            content=_no_report_html(),
            status_code=200,
        )
    return FileResponse(_REPORT_HTML, media_type="text/html")


@router.get("/coverage", summary="カバレッジレポートのトップページ")
async def get_coverage_report():
    """pytest-cov で生成したカバレッジ HTML レポートを配信する。"""
    if not _COVERAGE_HTML.exists():
        return HTMLResponse(
            content="<h1>カバレッジレポートが見つかりません</h1>"
                    "<p>まず <a href='/test-report/run'>テストを実行</a> してください。</p>",
            status_code=200,
        )
    return FileResponse(_COVERAGE_HTML, media_type="text/html")


@router.get("/junit.xml", summary="JUnit XML レポートを取得")
async def get_junit_xml():
    """JUnit XML 形式のレポートを返す（CI 連携用）。"""
    if not _JUNIT_XML.exists():
        raise HTTPException(status_code=404, detail="JUnit XML レポートが見つかりません")
    return FileResponse(_JUNIT_XML, media_type="application/xml")


@router.post("/run", summary="テストをバックグラウンドで実行")
async def run_tests(
    background_tasks: BackgroundTasks,
    markers: str = "",         # 例: "unit" または "unit or integration"
    test_path: str = "tests",  # 例: "tests/core" で特定ディレクトリのみ
):
    """pytest をバックグラウンドで実行しレポートを生成する。

    - markers: pytest の `-m` マーカー式（例: "unit", "not slow"）
    - test_path: テスト対象パス（例: "tests/core/test_invoice_validator.py"）
    """
    if _test_run_state["status"] == "running":
        return {"message": "テストは現在実行中です", "status": "running"}

    _test_run_state["status"] = "running"
    _test_run_state["started_at"] = datetime.now().isoformat()
    _test_run_state["completed_at"] = None
    _test_run_state["exit_code"] = None

    background_tasks.add_task(_run_pytest, markers=markers, test_path=test_path)

    return {
        "message": "テスト実行を開始しました",
        "status": "running",
        "started_at": _test_run_state["started_at"],
        "report_html_url": "/test-report/html",
    }


@router.get("/status", summary="テスト実行ステータス確認")
async def get_run_status():
    """現在のテスト実行ステータスを返す。"""
    return _test_run_state


# ── プライベート関数 ───────────────────────────────────────────────────

async def _run_pytest(markers: str = "", test_path: str = "tests") -> None:
    """pytest を subprocess で実行する。"""
    report_dir = _BACKEND_DIR / "test-reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    # tests/ ディレクトリを絶対パスに解決（cwd が変わっても安全）
    resolved_test_path = str((_BACKEND_DIR / test_path).resolve())

    cmd = [
        sys.executable, "-m", "pytest",
        resolved_test_path,
        f"--html={report_dir}/report.html",
        "--self-contained-html",
        f"--junitxml={report_dir}/junit.xml",
        "--cov=src",
        f"--cov-report=html:{report_dir}/coverage",
        "--cov-report=term-missing",
        "-v",
        "--tb=short",
        "--color=no",
        "--no-header",
        # pytest.ini の addopts を継承しないようにオーバーライド
        "--override-ini=addopts=",
    ]

    if markers:
        cmd += ["-m", markers]

    logger.info("pytest 実行: %s", " ".join(cmd))
    start = time.perf_counter()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(_BACKEND_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**__import__("os").environ,
                 "PYTHONPATH": str(_BACKEND_DIR),
                 "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
                 "OPENAI_API_KEY": __import__("os").environ.get("OPENAI_API_KEY", "test-key"),
                 "GEMINI_API_KEY": __import__("os").environ.get("GEMINI_API_KEY", "test-key"),
                 "AI_DEPLOYMENT_MODE": "cloud",
                 "UPLOAD_DIR": "/tmp/ocr_test_uploads",
                 "EXPORT_DIR": "/tmp/ocr_test_exports",
                 "ORIGINALS_DIR": "/tmp/ocr_test_originals",
                 "SECRET_KEY": "test-secret-key-for-tests-only"},
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        exit_code = proc.returncode

        elapsed = time.perf_counter() - start
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        logger.info("pytest 完了: exit_code=%d, elapsed=%.1fs\n%s",
                    exit_code, elapsed, stdout_text[-3000:])
        if stderr_text.strip():
            logger.warning("pytest stderr: %s", stderr_text[-2000:])

        # exit_code 1 = テスト失敗あり（正常終了）、0 = 全成功
        # exit_code 2+ = 設定エラーなど（異常）
        _test_run_state["status"] = "completed" if exit_code in (0, 1) else "failed"
        _test_run_state["exit_code"] = exit_code
        _test_run_state["completed_at"] = datetime.now().isoformat()
        _test_run_state["stdout"] = stdout_text[-5000:]

        # JUnit XML を解析してサマリーを保存
        if _JUNIT_XML.exists():
            try:
                _test_run_state["summary"] = _parse_junit_xml(_JUNIT_XML)
            except Exception as parse_exc:
                logger.warning("JUnit XML 解析エラー: %s", parse_exc)

    except Exception as exc:
        logger.error("pytest 実行エラー: %s", exc)
        _test_run_state["status"] = "failed"
        _test_run_state["completed_at"] = datetime.now().isoformat()
        _test_run_state["stdout"] = str(exc)


def _empty_summary() -> dict:
    """フィールドが揃った空のサマリーを返す（パース失敗時のフォールバック）。"""
    return {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "pass_rate": 0.0,
        "time_seconds": 0.0,
        "failed_cases": [],
    }


def _parse_junit_xml(xml_path: Path) -> dict:
    """JUnit XML からテスト結果サマリーを抽出する。

    pytest が生成する形式を 2 パターン処理する:
      - <testsuites><testsuite ...>...</testsuite></testsuites>  (xunit2 / default)
      - <testsuite ...>...</testsuite>                            (legacy)

    複数の <testsuite> 要素がある場合はすべてを集計する。
    解析に失敗した場合でも例外を送出せず、空のサマリーを返す。
    """
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        logger.warning("JUnit XML ParseError: %s", exc)
        return _empty_summary()

    root = tree.getroot()

    # すべての <testsuite> 要素を収集して集計する
    if root.tag == "testsuite":
        suites = [root]
    else:
        # <testsuites> の直接の子 → さらにネストがある場合も含める
        suites = root.findall(".//testsuite")

    if not suites:
        logger.warning("testsuite 要素が見つかりません: %s", xml_path)
        return _empty_summary()

    total = errors = failures = skipped = 0
    time_sec = 0.0

    for s in suites:
        t = int(s.get("tests", 0) or 0)
        # tests=0 のラッパー testsuite は集計から除外（子 testsuite に実データがある）
        if t == 0 and len(suites) > 1:
            continue
        total    += t
        errors   += int(s.get("errors",   0) or 0)
        failures += int(s.get("failures", 0) or 0)
        skipped  += int(s.get("skipped",  0) or 0)
        time_sec += float(s.get("time", 0) or 0)

    # どの suite にも tests > 0 がなかった場合は単純に全要素を合算
    if total == 0 and suites:
        for s in suites:
            total    += int(s.get("tests",    0) or 0)
            errors   += int(s.get("errors",   0) or 0)
            failures += int(s.get("failures", 0) or 0)
            skipped  += int(s.get("skipped",  0) or 0)

    passed = max(0, total - errors - failures - skipped)

    # 失敗テストの詳細（最大 20 件）
    failed_cases: list[dict] = []
    for tc in root.findall(".//testcase"):
        failure = tc.find("failure")
        error_elem = tc.find("error")
        if failure is not None or error_elem is not None:
            msg_elem = failure if failure is not None else error_elem
            failed_cases.append({
                "name":      tc.get("name", ""),
                "classname": tc.get("classname", ""),
                "message":   (msg_elem.get("message", "") or "")[:200],
            })

    return {
        "total":        total,
        "passed":       passed,
        "failed":       failures,
        "errors":       errors,
        "skipped":      skipped,
        "pass_rate":    round(passed / total * 100, 1) if total > 0 else 0.0,
        "time_seconds": round(time_sec, 2),
        "failed_cases": failed_cases[:20],
    }


def _no_report_html() -> str:
    """レポートが存在しない場合の案内 HTML。"""
    return """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <title>テストレポート — 未実行</title>
  <style>
    body { font-family: sans-serif; max-width: 600px; margin: 60px auto; color: #333; }
    h1 { color: #1a1a2e; }
    .btn {
      display: inline-block; padding: 12px 24px; background: #4f46e5;
      color: white; border-radius: 6px; text-decoration: none; margin: 8px 0;
    }
    pre { background: #f5f5f5; padding: 12px; border-radius: 4px; }
  </style>
</head>
<body>
  <h1>テストレポート</h1>
  <p>テストがまだ実行されていません。</p>
  <p>以下のいずれかの方法でテストを実行してください:</p>
  <h2>1. Web API から実行</h2>
  <a class="btn" href="/test-report/run" onclick="
    fetch('/test-report/run', {method:'POST'})
      .then(r=>r.json())
      .then(d=>{ alert(d.message); location.reload(); });
    return false;
  ">テストを実行する</a>
  <h2>2. コマンドラインから実行</h2>
  <pre>cd C:\\devlop\\ocr\\backend
run_tests.bat</pre>
  <h2>3. Docker コンテナ内で実行</h2>
  <pre>docker exec ocr_backend python -m pytest tests/ -v</pre>
</body>
</html>
"""
