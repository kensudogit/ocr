#!/bin/bash
# ──────────────────────────────────────────────────────────────────────
# 税理士事務所向け OCR システム 起動スクリプト（開発環境）
# ──────────────────────────────────────────────────────────────────────
set -e

echo "🚀 OCR仕訳システム 起動中..."
echo ""

# ── Docker が利用可能な場合は Docker Compose で起動 ──────────────────
if command -v docker-compose &> /dev/null; then
    echo "📦 Docker Compose で起動します..."
    docker-compose up --build
    exit 0
fi

# ── ローカル開発環境（Docker なし） ─────────────────────────────────
echo "⚠️  Docker が見つかりません。ローカル環境で起動します。"
echo ""
echo "前提条件:"
echo "  - Python 3.11+"
echo "  - Node.js 20+"
echo "  - PostgreSQL（別途起動してください）"
echo ""

# バックエンド起動
echo "🐍 FastAPI バックエンドを起動中 (port: 8000)..."
cd backend
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt -q

# .env が存在しない場合は example をコピー
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "📝 .env ファイルを作成しました。データベース設定を確認してください。"
fi

uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
cd ..

# フロントエンド起動
echo "⚛️  Next.js フロントエンドを起動中 (port: 3000)..."
cd frontend
npm install -q
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "✅ 起動完了"
echo "   フロントエンド: http://localhost:3000"
echo "   バックエンドAPI: http://localhost:8000"
echo "   API ドキュメント: http://localhost:8000/docs"
echo ""
echo "停止するには Ctrl+C を押してください"

# 終了シグナルを受け取ったら子プロセスを終了
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
