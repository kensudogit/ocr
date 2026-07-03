@echo off
chcp 932 >nul 2>&1

REM ============================================================
REM  OCR System - Test Runner (Windows)
REM ============================================================
REM
REM Usage:
REM   run_tests.bat              Run all tests
REM   run_tests.bat unit         Unit tests only
REM   run_tests.bat invoice      Invoice validator tests
REM   run_tests.bat pii          PII masker tests
REM   run_tests.bat security     Security tests
REM   run_tests.bat fast         Skip slow tests
REM   run_tests.bat api          API integration tests
REM   run_tests.bat core         Core module tests
REM
REM Output:
REM   test-reports\report.html       pytest-html report
REM   test-reports\coverage\         Coverage report
REM   test-reports\junit.xml         JUnit XML (for CI)
REM
REM Web view (after backend starts):
REM   http://localhost:8000/test-report/html
REM ============================================================

setlocal

REM === Environment Variables ===
set PYTHONPATH=%~dp0
set DATABASE_URL=sqlite+aiosqlite:///
set OPENAI_API_KEY=test-key
set GEMINI_API_KEY=test-key
set AI_DEPLOYMENT_MODE=cloud
set UPLOAD_DIR=%TEMP%\ocr_test_uploads
set EXPORT_DIR=%TEMP%\ocr_test_exports
set ORIGINALS_DIR=%TEMP%\ocr_test_originals
set SECRET_KEY=test-secret-key-for-tests-only

REM === Create report directory ===
if not exist "test-reports" mkdir test-reports

REM === Marker filter from first argument ===
set MARKER_OPT=
set TEST_PATH=tests

if "%1"=="unit"                    set MARKER_OPT=-m unit
if "%1"=="invoice"                 set MARKER_OPT=-m invoice
if "%1"=="pii"                     set MARKER_OPT=-m pii
if "%1"=="security"                set MARKER_OPT=-m security
if "%1"=="electronic_bookkeeping"  set MARKER_OPT=-m electronic_bookkeeping
if "%1"=="fast"                    set MARKER_OPT=-m "not slow"
if "%1"=="api"                     set TEST_PATH=tests\api
if "%1"=="core"                    set TEST_PATH=tests\core

echo ============================================================
echo  OCR System - Running Tests
echo  Filter : %1
echo  Time   : %DATE% %TIME%
echo ============================================================

python -m pytest %TEST_PATH% ^
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
echo ============================================================
if %EXIT_CODE%==0 (
    echo  [PASS] All tests passed!
) else (
    echo  [FAIL] Some tests failed. Exit code: %EXIT_CODE%
)
echo ============================================================
echo  HTML Report : test-reports\report.html
echo  Coverage    : test-reports\coverage\index.html
echo  Web View    : http://localhost:8000/test-report/html
echo ============================================================
echo.

exit /b %EXIT_CODE%
