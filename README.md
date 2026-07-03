# 税理士事務所向け OCR 自動仕訳システム

地方の中規模税理士事務所（記帳代行含む、9名規模）が月500枚以上の書類を処理するための  
**OCR 自動仕訳システム**です。手入力工数 月500時間超を大幅に削減します。

---

## 解決する課題

| Before | After |
|--------|-------|
| レシート・領収書の手入力 | 📷 写真を撮るだけで自動読み取り |
| 月500時間超の入力作業 | ⚡ OCR＋AIで初稿を自動生成 |
| 感熱紙の読み取り困難 | 🔬 専用前処理で薄い文字も認識 |
| 確定申告期（2〜3月）の繁忙 | 📦 一括アップロードで500枚を一括処理 |
| 会計ソフトへの手動入力 | 📤 freee/MF/弥生会計に直接インポート |

---

## 対応書類

| 書類種別 | 特性 | 対応方法 |
|----------|------|----------|
| **感熱紙レシート** | 低コントラスト・背景グレー | CLAHE＋ガンマ補正 |
| **手書き領収書** | 薄い筆跡・手ブレ | 膨張処理＋シャープニング |
| **請求書（A4/PDF）** | 適格請求書番号・支払期日 | PDF変換＋構造解析 |
| **カード明細** | 細かい文字・印刷ムラ | ガンマ補正＋OCR精度向上 |

---

## システム構成

```
ocr/
├── backend/              # FastAPI バックエンド
│   ├── src/
│   │   ├── main.py       # アプリケーションエントリーポイント
│   │   ├── config.py     # 設定管理
│   │   ├── api/
│   │   │   ├── upload.py       # アップロード・OCR処理API
│   │   │   ├── documents.py    # 書類CRUD・承認API
│   │   │   └── export_api.py   # 会計ソフト連携エクスポートAPI
│   │   ├── core/
│   │   │   ├── preprocessor.py # 画像前処理（感熱紙・手書き対応）
│   │   │   ├── ocr_engine.py   # OCRエンジン（PaddleOCR/Google Vision）
│   │   │   ├── extractor.py    # データ抽出（日付・金額・取引先等）
│   │   │   ├── classifier.py   # 書類種別分類
│   │   │   └── exporter.py     # 会計ソフト連携CSV生成
│   │   └── db/
│   │       ├── database.py     # DB接続
│   │       └── models.py       # SQLAlchemyモデル
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/             # Next.js フロントエンド
│   ├── app/
│   │   ├── page.tsx           # ダッシュボード
│   │   ├── upload/page.tsx    # アップロードページ
│   │   ├── review/page.tsx    # 確認・修正ページ
│   │   └── export/page.tsx    # エクスポートページ
│   ├── components/
│   │   └── NavBar.tsx
│   └── lib/
│       └── api.ts             # APIクライアント
├── docker-compose.yml
├── start.bat             # Windows 起動スクリプト
├── start.sh              # Linux/Mac 起動スクリプト
└── README.md
```

---

## 画面構成

### ダッシュボード (`/`)
- 今月の処理枚数・確認待ち件数・承認済み合計金額
- 書類種別・ステータス内訳グラフ
- 最近の書類一覧

### アップロード (`/upload`)
- **1件ずつ**: ドラッグ＆ドロップ → 即時OCR処理（10〜30秒）
- **一括**: 複数ファイル選択 → バックグラウンドで一括処理 → 進捗バー表示

### 確認・修正 (`/review`)
- OCR 抽出結果の確認（信頼度カラーコード表示）
- 手動修正フォーム（取引日・金額・取引先・勘定科目・税区分）
- 承認 / 差し戻し（差し戻し理由入力可）
- OCR 生テキスト・明細行表示

### エクスポート (`/export`)
- エクスポート先選択（freee / マネーフォワード / 弥生会計 / 汎用CSV）
- 承認済み書類の一覧表示・チェックボックス選択
- CSV ダウンロード（文字コード自動設定）

---

## 起動方法

### Docker を使用（推奨）

```bash
# 起動
docker-compose up --build

# アクセス
# フロントエンド: http://localhost:3000
# バックエンドAPI: http://localhost:8000/docs
```

### ローカル環境

**Windows:**
```bat
start.bat
```

**Linux / Mac:**
```bash
chmod +x start.sh
./start.sh
```

**手動起動:**
```bash
# バックエンド
cd backend
python -m venv venv
source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env         # 設定ファイルを作成
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

# フロントエンド（別ターミナル）
cd frontend
npm install
npm run dev
```

---

## 環境変数設定

`backend/.env` を編集して設定します:

```env
# データベース（PostgreSQL 必須）
DATABASE_URL=postgresql+psycopg://ocr:ocr_pass@localhost:5432/ocr_db

# OCR エンジン
# "paddle" = ローカルPaddleOCR（デフォルト、API費用なし）
# "auto"   = PaddleOCR → 信頼度低の場合 Google Vision にフォールバック
OCR_ENGINE=auto

# Google Cloud Vision API（手書き書類の精度向上、オプション）
GOOGLE_VISION_API_KEY=your_api_key_here

# 感熱紙前処理（true推奨）
ENHANCE_THERMAL_PAPER=true
AUTO_ROTATE=true
DENOISE_LEVEL=2
```

---

## 会計ソフト連携フォーマット

| ソフト | ファイル名 | 文字コード | 備考 |
|--------|-----------|-----------|------|
| freee会計 | `freee_YYYYMMDD.csv` | UTF-8 BOM | 仕訳インポート形式 |
| マネーフォワード | `mf_YYYYMMDD.csv` | UTF-8 BOM | 仕訳帳インポート形式 |
| 弥生会計 | `yayoi_YYYYMMDD.csv` | Shift-JIS | 仕訳日記帳形式 |
| 汎用CSV | `generic_YYYYMMDD.csv` | UTF-8 BOM | 全フィールド出力 |

---

## 全体フロー（7 ステップ）

```
【Step 1】入力
  スマホ撮影 / Excel 受領 / スキャン画像 / PDF
  単一アップロード or 一括アップロード（200件/回）
       ↓
【Step 2】前処理（ImagePreprocessor）
  ・感熱紙コントラスト強調（CLAHE + ガンマ補正）
  ・傾き検出 & 補正（Hough変換）
  ・ノイズ除去（FastNlMeansDenoising）
  ・適応的二値化（OCR 精度向上）
  ・PDF → 複数ページ画像変換
       ↓
【Step 3】AI-OCR（VlmExtractor）
  優先: OpenAI GPT-4o / GPT-4o-mini
  代替: Google Gemini 2.0 Flash
  FB:   PaddleOCR + 正規表現（API なし環境）

  抽出フィールド:
  ・取引日（令和/平成/西暦すべて対応）
  ・合計金額 / 税抜金額 / 消費税（10% / 8%軽減）
  ・取引先名 / 住所 / 電話番号
  ・適格請求書番号（T + 13桁）
  ・請求書番号 / 支払方法
  ・勘定科目候補 / 税区分候補
  ・明細行（品目・数量・単価・金額）
       ↓
【Step 4】ルール層（RuleEngine）
  ・顧問先ごとの「取引先 → 勘定科目 / 税区分」マッピング
  ・過去の承認済み仕訳から自動学習（DBに永続化）
  ・完全一致(97%) → 部分一致(85%) → キーワード(70%) の優先順位
       ↓
【Step 5】信頼度判定（ConfidenceScorer）
  スコア算出:
    取引日(20%) + 金額(30%) + 取引先(20%) + 消費税(15%) + 検算(15%)
  検算: 小計 + 消費税10% + 消費税8% = 合計（誤差1円 or 0.5%許容）

  3 段階自動仕分け:
  ✅ 自動確定（≥85%）: 担当者確認不要、自動承認
  ⚠️ 要確認  (55〜85%): 確認画面に表示
  ✏️ 手入力  (<55%):  精度低、手動入力を促す
       ↓
【Step 6】確認 UI（Next.js）
  ・「要確認」のみ絞り込み表示
  ・原本画像 ‖ 抽出データ の並列 3カラムレイアウト
  ・フィールド別信頼度カラーコード
  ・リアルタイム検算表示
  ・承認 → ルールエンジンに学習
       ↓
【Step 7】連携出力
  freee:         公式 API で取引（支出）を直接登録
  マネーフォワード: CSV 仕訳インポート（UTF-8 BOM）
  弥生会計:        CSV 仕訳日記帳（Shift-JIS）
  汎用 CSV:        全フィールド出力
```

---

## 技術スタック

| 領域 | 技術 |
|------|------|
| バックエンド | Python 3.11 + FastAPI |
| OCR（主） | PaddleOCR 2.9.1（日本語モデル） |
| OCR（補助） | Google Cloud Vision API |
| 画像処理 | OpenCV + Pillow |
| データベース | PostgreSQL 16 |
| フロントエンド | Next.js 15 (App Router) + TypeScript |
| スタイリング | Tailwind CSS |
| コンテナ | Docker + Docker Compose |

---

## ライセンス

MIT License
