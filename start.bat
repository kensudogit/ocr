@echo off
REM ──────────────────────────────────────────────────────────────────────
REM 税理士事務所向け OCR システム 起動スクリプト（Windows）
REM ──────────────────────────────────────────────────────────────────────
echo.
echo [INFO] OCR仕訳システム 起動中...
echo.

REM ── Docker Compose 優先 ────────────────────────────────────────────
WHERE docker-compose >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    echo [INFO] Docker Compose で起動します...
    docker-compose up --build
    goto :EOF
)

echo [WARNING] Docker が見つかりません。ローカル環境で起動します。
echo.

REM ── バックエンド起動 ────────────────────────────────────────────────
echo [INFO] FastAPI バックエンドを起動中 (port: 8000)...
cd backend

IF NOT EXIST venv (
    python -m venv venv
)
call venv\Scripts\activate.bat
pip install -r requirements.txt -q

IF NOT EXIST .env (
    copy .env.example .env
    echo [INFO] .env ファイルを作成しました。設定を確認してください。
)

start /B uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
cd ..

REM ── フロントエンド起動 ──────────────────────────────────────────────
echo [INFO] Next.js フロントエンドを起動中 (port: 3000)...
cd frontend
call npm install
start /B npm run dev
cd ..

echo.
echo [OK] 起動完了
echo    フロントエンド: http://localhost:3000
echo    バックエンドAPI: http://localhost:8000
echo    API ドキュメント: http://localhost:8000/docs
echo.
echo 停止するには各ターミナルウィンドウを閉じてください
pause
