@echo off
:: ═══════════════════════════════════════════════════════════════════
:: OCR システム テスト実行スクリプト（Windows）
:: ═══════════════════════════════════════════════════════════════════
::
:: 使い方:
::   run_tests.bat             全テスト実行
::   run_tests.bat unit        Unit テストのみ
::   run_tests.bat invoice     インボイス検証テストのみ
::   run_tests.bat fast        slow マーカーなしのテストのみ
::   run_tests.bat api         API テストのみ
::
:: 出力先:
::   test-reports\report.html      pytest-html レポート
::   test-reports\coverage\        カバレッジレポート
::   test-reports\junit.xml        JUnit XML（CI 連携用）
::
:: ブラウザで確認:
::   test-reports\report.html を直接開く
::   または バックエンド起動後: http://localhost:8000/test-report/html
:: ═══════════════════════════════════════════════════════════════════

setlocal
set PYTHONPATH=%~dp0
set DATABASE_URL=sqlite+aiosqlite:///:memory:
set OPENAI_API_KEY=test-key
set GEMINI_API_KEY=test-key
set AI_DEPLOYMENT_MODE=cloud
set UPLOAD_DIR=%TEMP%\ocr_test_uploads
set EXPORT_DIR=%TEMP%\ocr_test_exports
set ORIGINALS_DIR=%TEMP%\ocr_test_originals
set SECRET_KEY=test-secret-key-for-tests-only

:: レポートディレクトリ作成
if not exist "test-reports" mkdir test-reports

:: マーカーフィルタ
set MARKER_OPT=
if "%1"=="unit" set MARKER_OPT=-m unit
if "%1"=="invoice" set MARKER_OPT=-m invoice
if "%1"=="pii" set MARKER_OPT=-m pii
if "%1"=="security" set MARKER_OPT=-m security
if "%1"=="electronic_bookkeeping" set MARKER_OPT=-m electronic_bookkeeping
if "%1"=="fast" set MARKER_OPT=-m "not slow"
if "%1"=="api" set MARKER_OPT=tests\api
if "%1"=="core" set MARKER_OPT=tests\core

echo ================================================================
echo  OCR システム テスト実行
echo  フィルタ: %1
echo  開始時刻: %DATE% %TIME%
echo ================================================================

python -m pytest tests ^
    --html=test-reports/report.html ^
    --self-contained-html ^
    --junitxml=test-reports/junit.xml ^
    --cov=src ^
    --cov-report=html:test-reports/coverage ^
    --cov-report=term-missing ^
    -v ^
    --tb=short ^
    --color=yes ^
    %MARKER_OPT%

set EXIT_CODE=%ERRORLEVEL%

echo.
echo ================================================================
if %EXIT_CODE%==0 (
    echo  [PASS] 全テスト合格
) else (
    echo  [FAIL] テスト失敗 (exit code: %EXIT_CODE%)
)
echo ================================================================
echo  レポート: test-reports\report.html
echo  カバレッジ: test-reports\coverage\index.html
echo  Web 確認: http://localhost:8000/test-report/html
echo ================================================================

:: レポートをブラウザで自動表示（オプション: 必要に応じてコメントアウト）
:: start "" "test-reports\report.html"

exit /b %EXIT_CODE%
