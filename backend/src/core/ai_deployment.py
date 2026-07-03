"""AI デプロイメントモード設定モジュール。

3つの構成を提供:

① クラウドAI（ZDR設定）
  - OpenAI: Zero Data Retention（学習オプトアウト）ヘッダ
  - Google Gemini: Vertex AI (Japan) でデータ国内固定
  - 利点: 高精度、低コスト、セットアップ簡単

② ハイブリッド
  - 機微情報（マイナンバー・口座番号）は PiiMasker でローカルマスク
  - マスク済みテキスト/画像をクラウドに送信
  - 利点: セキュリティとコストのバランス

③ オンプレ完結
  - PaddleOCR（ローカル OCR）
  - AWS Bedrock（東京/大阪リージョン）+ 閉域網
  - Ollama + LLaMA 3.2 Vision（完全ローカル）
  - 利点: 機密データがクラウドに出ない

設定方法: .env の AI_DEPLOYMENT_MODE で切り替え
  AI_DEPLOYMENT_MODE=cloud      # ①
  AI_DEPLOYMENT_MODE=hybrid     # ②
  AI_DEPLOYMENT_MODE=bedrock    # AWS Bedrock
  AI_DEPLOYMENT_MODE=onprem     # ③ オンプレ完結
"""
from __future__ import annotations

import logging
from enum import Enum

from src.config import settings

logger = logging.getLogger(__name__)


class AiDeploymentMode(str, Enum):
    CLOUD   = "cloud"    # OpenAI / Gemini（ZDR設定）
    HYBRID  = "hybrid"   # ローカルPIIマスク → クラウドAI
    BEDROCK = "bedrock"  # AWS Bedrock（東京/大阪リージョン）
    VERTEX  = "vertex"   # Google Vertex AI（日本リージョン）
    ONPREM  = "onprem"   # 完全ローカル（PaddleOCR + Ollama）


class AiDeploymentConfig:
    """AI デプロイメント設定の中央管理クラス。"""

    def __init__(self) -> None:
        self.mode = AiDeploymentMode(settings.ai_deployment_mode)
        logger.info("AI デプロイメントモード: %s", self.mode.value)

    @property
    def requires_pii_masking(self) -> bool:
        """クラウドに送信前に PII マスクが必要かどうか。"""
        return self.mode in (AiDeploymentMode.HYBRID,)

    @property
    def uses_cloud_ai(self) -> bool:
        return self.mode in (
            AiDeploymentMode.CLOUD,
            AiDeploymentMode.HYBRID,
            AiDeploymentMode.BEDROCK,
            AiDeploymentMode.VERTEX,
        )

    @property
    def is_fully_local(self) -> bool:
        return self.mode == AiDeploymentMode.ONPREM


class ZdrOpenAiClient:
    """Zero Data Retention 設定付き OpenAI クライアント。

    ZDR（Zero Data Retention）:
      - OpenAI API は Enterprise / API 利用では学習に使用しないことを明言
      - 追加保護として「openai-processing-timeout」「no-cache」ヘッダを付与
      - ビジネスプランでは `/v1/chat/completions` に ZDR パラメータ可能

    OpenAI の ZDR ポリシー:
      API 経由のデータは学習に使用されない（利用規約 Section 3）
      Enterprise では Data Processing Addendum（DPA）で保証
    """

    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY が設定されていません")
        from openai import OpenAI
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            # ZDR 推奨設定: タイムアウトを短めに（残留なし）
            timeout=60.0,
            max_retries=2,
            default_headers={
                "X-Request-No-Cache": "true",  # キャッシュ無効化
            },
        )

    def create_completion(self, messages: list[dict], model: str | None = None, **kwargs):
        """ZDR 設定付きでチャット完了を実行する。"""
        return self._client.chat.completions.create(
            model=model or settings.openai_model,
            messages=messages,
            **kwargs,
        )


class BedrockClient:
    """AWS Bedrock クライアント（東京/大阪リージョン）。

    東京リージョン (ap-northeast-1) または大阪リージョン (ap-northeast-3) で
    データを国内に閉じてAI処理する。

    利用可能なモデル:
      - anthropic.claude-3-5-sonnet-20241022-v2:0（推奨）
      - anthropic.claude-3-haiku-20240307-v1:0（高速・低コスト）
      - amazon.nova-pro-v1:0

    前提:
      - AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY が設定済み
      - Bedrock のモデルアクセスが有効化済み
    """

    def __init__(self) -> None:
        try:
            import boto3
            self._bedrock = boto3.client(
                "bedrock-runtime",
                region_name=settings.aws_region,  # ap-northeast-1 (東京)
            )
            logger.info("AWS Bedrock クライアント初期化（リージョン: %s）", settings.aws_region)
        except ImportError:
            raise ImportError("boto3 が見つかりません: pip install boto3")

    async def invoke_with_image(
        self,
        image_b64: str,
        prompt: str,
        model_id: str | None = None,
    ) -> str:
        """Bedrock で画像付きリクエストを実行する。"""
        import asyncio
        import json

        model = model_id or settings.bedrock_model_id

        # Anthropic Claude Messages API 形式
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._bedrock.invoke_model(
                modelId=model,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            ),
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]


class VertexAiClient:
    """Google Vertex AI クライアント（日本リージョン）。

    asia-northeast1（東京）または asia-northeast2（大阪）で処理。
    データ常駐ポリシー（Data Residency）で国内保管を保証。
    """

    def __init__(self) -> None:
        try:
            import vertexai
            vertexai.init(
                project=settings.gcp_project_id,
                location=settings.vertex_location,  # asia-northeast1 (東京)
            )
            logger.info("Vertex AI 初期化（ロケーション: %s）", settings.vertex_location)
        except ImportError:
            raise ImportError("google-cloud-aiplatform が見つかりません: pip install google-cloud-aiplatform")

    async def generate_with_image(self, image_bytes: bytes, prompt: str) -> str:
        """Vertex AI Gemini で画像付きリクエストを実行する。"""
        import asyncio
        from vertexai.generative_models import GenerativeModel, Part, Image

        model = GenerativeModel("gemini-2.0-flash")
        image_part = Part.from_data(image_bytes, mime_type="image/png")

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content([prompt, image_part]),
        )
        return response.text


class OllamaClient:
    """Ollama 完全ローカル AI クライアント。

    対応モデル（Vision 対応）:
      - llava:34b         （高精度）
      - llama3.2-vision   （バランス）
      - minicpm-v         （軽量）

    セットアップ:
      ollama pull llama3.2-vision
      ollama serve

    特徴:
      - 完全ローカル実行（インターネット不要）
      - GPU があれば高速、CPU でも動作可能
      - データが外部に出ない
    """

    BASE_URL = "http://localhost:11434"

    async def generate_with_image(self, image_b64: str, prompt: str) -> str:
        import asyncio
        import httpx

        payload = {
            "model": settings.ollama_model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "options": {
                "temperature": 0,
                "num_ctx": 4096,
            },
        }

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{self.BASE_URL}/api/generate", json=payload)
            response.raise_for_status()
            return response.json().get("response", "")


# ── 設定ファクトリ ─────────────────────────────────────────────────────

def get_deployment_config() -> AiDeploymentConfig:
    """現在のデプロイメント設定を返す。"""
    return AiDeploymentConfig()


def get_ai_client(mode: AiDeploymentMode | None = None):
    """指定したモードに対応する AI クライアントを返す。"""
    m = mode or AiDeploymentMode(settings.ai_deployment_mode)
    if m == AiDeploymentMode.CLOUD:
        return ZdrOpenAiClient()
    elif m == AiDeploymentMode.HYBRID:
        return ZdrOpenAiClient()  # 呼び出し前に PiiMasker を適用
    elif m == AiDeploymentMode.BEDROCK:
        return BedrockClient()
    elif m == AiDeploymentMode.VERTEX:
        return VertexAiClient()
    elif m == AiDeploymentMode.ONPREM:
        return OllamaClient()
    return ZdrOpenAiClient()
