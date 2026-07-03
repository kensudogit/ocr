# ═══════════════════════════════════════════════════════════════════
# OCR システム Makefile（Linux / macOS / WSL 用）
# ═══════════════════════════════════════════════════════════════════

PYTHONPATH ?= .
PYTEST_OPTS ?= --html=test-reports/report.html \
               --self-contained-html \
               --junitxml=test-reports/junit.xml \
               --cov=src \
               --cov-report=html:test-reports/coverage \
               --cov-report=term-missing \
               -v --tb=short

export DATABASE_URL = sqlite+aiosqlite:///:memory:
export OPENAI_API_KEY = test-key
export GEMINI_API_KEY = test-key
export AI_DEPLOYMENT_MODE = cloud
export UPLOAD_DIR = /tmp/ocr_test_uploads
export EXPORT_DIR = /tmp/ocr_test_exports
export ORIGINALS_DIR = /tmp/ocr_test_originals
export SECRET_KEY = test-secret-key-for-tests-only

.PHONY: test test-unit test-core test-api test-invoice test-pii test-security \
        test-coverage test-fast install clean open-report

## 全テスト実行
test:
	@mkdir -p test-reports
	python -m pytest tests/ $(PYTEST_OPTS)

## Unit テストのみ（外部依存なし）
test-unit:
	@mkdir -p test-reports
	python -m pytest tests/ $(PYTEST_OPTS) -m unit

## Core 層テストのみ
test-core:
	@mkdir -p test-reports
	python -m pytest tests/core/ $(PYTEST_OPTS)

## API 統合テストのみ
test-api:
	@mkdir -p test-reports
	python -m pytest tests/api/ $(PYTEST_OPTS)

## インボイス番号検証テストのみ
test-invoice:
	@mkdir -p test-reports
	python -m pytest tests/ $(PYTEST_OPTS) -m invoice

## PII マスクテストのみ
test-pii:
	@mkdir -p test-reports
	python -m pytest tests/ $(PYTEST_OPTS) -m pii

## セキュリティ・電帳法テスト
test-security:
	@mkdir -p test-reports
	python -m pytest tests/ $(PYTEST_OPTS) -m "security or electronic_bookkeeping"

## カバレッジのみ（レポートなし・高速）
test-coverage:
	python -m pytest tests/ --cov=src --cov-report=term-missing -q

## slow なしの高速テスト
test-fast:
	@mkdir -p test-reports
	python -m pytest tests/ $(PYTEST_OPTS) -m "not slow"

## 依存関係インストール（テスト用追加パッケージ含む）
install:
	pip install -r requirements.txt
	pip install pytest pytest-asyncio pytest-html pytest-cov \
	            aiosqlite httpx coverage

## テストレポートをブラウザで開く
open-report:
	@if [ -f test-reports/report.html ]; then \
	    open test-reports/report.html 2>/dev/null || \
	    xdg-open test-reports/report.html 2>/dev/null || \
	    echo "ブラウザで test-reports/report.html を開いてください"; \
	else \
	    echo "レポートが見つかりません。make test を先に実行してください"; \
	fi

## ビルド成果物のクリーン
clean:
	rm -rf test-reports/ .coverage .pytest_cache __pycache__
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
