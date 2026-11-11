import json
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./video_ai.db"
    redis_url: str | None = None
    artifact_dir: Path = Path("./artifacts")
    default_project_budget_cents: int = 1_000
    allow_live_publish: bool = False
    youtube_api_base: str = "https://www.googleapis.com/upload/youtube/v3"
    youtube_access_token: str | None = None
    tiktok_api_base: str = "https://open.tiktokapis.com/v2"
    tiktok_access_token: str | None = None
    cors_origins: str = "http://localhost:3000"
    credential_secret: str = "local-development-only-change-me"
    oauth_redirect_base: str = "http://localhost:3000/api/v1/oauth/callback"
    web_base_url: str = "http://localhost:3000"
    youtube_client_id: str | None = None
    youtube_client_secret: str | None = None
    tiktok_client_key: str | None = None
    tiktok_client_secret: str | None = None

    jwt_secret: str = "local-development-only-jwt-secret-change-me"
    jwt_ttl_minutes: int = 60 * 12
    session_cookie: str = "narra_session"
    cookie_secure: bool = False

    s3_endpoint: str | None = None
    s3_public_endpoint: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "video-ai-local"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    signed_url_ttl_seconds: int = 900
    upload_max_bytes: int = 524_288_000

    kokoro_voice: str = "pf_dora"
    render_max_attempts: int = 3

    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_chat_deployment: str | None = None
    azure_openai_transcribe_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    # GPT-5 / o-series: max_completion_tokens instead of max_tokens, default temperature only.
    azure_openai_reasoning: bool = True
    azure_openai_min_completion_tokens: int = 16000
    azure_openai_reasoning_effort: str | None = "low"
    azure_openai_timeout_seconds: float = 300
    # Price per million tokens, in cents of the budget currency; adjust to your Azure contract.
    azure_input_cents_per_mtok: int = 250
    azure_output_cents_per_mtok: int = 1000
    azure_transcribe_cents_per_minute: int = 1

    tavily_api_key: str | None = None
    youtube_api_key: str | None = None
    pexels_api_key: str | None = None
    pixabay_api_key: str | None = None
    # Contact (URL or e-mail) sent in the media bot User-Agent; Wikimedia blocks anonymous bots.
    media_contact: str | None = None
    research_article_count: int = 5
    research_video_count: int = 6

    fair_use_clips_enabled: bool = False
    fair_use_max_clip_seconds: float = 8
    fair_use_max_ratio: float = 0.2
    autopilot_default_enabled: bool = False

    # Optional JSON with the Azure OpenAI settings (keys below); never commit it.
    azure_openai_config_file: Path = Path("config/azure-openai.json")
    azure_openai_config_source: str = "env"


AZURE_JSON_KEYS = {
    "endpoint": "azure_openai_endpoint",
    "api_key": "azure_openai_api_key",
    "chat_deployment": "azure_openai_chat_deployment",
    "transcribe_deployment": "azure_openai_transcribe_deployment",
    "api_version": "azure_openai_api_version",
    "reasoning": "azure_openai_reasoning",
    "reasoning_effort": "azure_openai_reasoning_effort",
    "min_completion_tokens": "azure_openai_min_completion_tokens",
    "timeout_seconds": "azure_openai_timeout_seconds",
    "input_cents_per_mtok": "azure_input_cents_per_mtok",
    "output_cents_per_mtok": "azure_output_cents_per_mtok",
    "transcribe_cents_per_minute": "azure_transcribe_cents_per_minute",
}


def _find_config(path: Path) -> Path | None:
    if path.is_absolute():
        return path if path.is_file() else None
    # Relative paths resolve from the working directory or the repository root (apps/api/app/config.py -> repo).
    for base in (Path.cwd(), Path(__file__).resolve().parents[3]):
        candidate = base / path
        if candidate.is_file():
            return candidate
    return None


def apply_azure_json(settings: Settings) -> Settings:
    """Fills Azure fields from the JSON file; a non-empty value set in the environment or .env still wins."""
    path = _find_config(settings.azure_openai_config_file)
    if path is None:
        return settings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Não foi possível ler {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} deve conter um objeto JSON")
    unknown = sorted(set(data) - set(AZURE_JSON_KEYS))
    if unknown:
        raise ValueError(f"Chaves desconhecidas em {path}: {', '.join(unknown)}")
    explicit = {
        field
        for field in settings.model_fields_set
        if getattr(settings, field) not in (None, "")
    }
    updates = {
        field: data[key]
        for key, field in AZURE_JSON_KEYS.items()
        if key in data and data[key] not in (None, "") and field not in explicit
    }
    if not updates:
        return settings
    merged = Settings.model_validate({**settings.model_dump(), **updates})
    merged.azure_openai_config_source = str(path)
    return merged


@lru_cache
def get_settings() -> Settings:
    return apply_azure_json(Settings())
