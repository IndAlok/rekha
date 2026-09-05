from pathlib import Path
from tempfile import gettempdir

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = f"sqlite+pysqlite:///{Path(gettempdir()) / 'rekha.db'}"
    rekha_env: str = "dev"
    rekha_timezone: str = "Asia/Kolkata"
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    # OPENAI_* names. The client is OpenAI-shaped. Default host is Groq.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.groq.com/openai/v1"
    openai_model: str = "llama-3.3-70b-versatile"
    comms_adapter: str = "file"
    payment_link_budget: int = 30
    cors_origins: str = "*"
    auto_eval_on_boot: bool = True
    ops_token: str = ""
    payments_adapter: str = "sandbox"


settings = Settings()


def cors_origin_list() -> list[str]:
    raw = settings.cors_origins.strip()
    if raw == "*":
        return ["*"]
    return [part.strip() for part in raw.split(",") if part.strip()]
