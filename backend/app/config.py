from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://warren:warren@db:5432/warren"
    REDIS_URL: str = "redis://redis:6379/0"
    ALPHA_VANTAGE_API_KEY: str = ""
    FRED_API_KEY: str = ""
    FINNHUB_API_KEY: str = ""
    API_KEY: str = ""
    # Notification provider: "signal" (default), "telegram", or "none".
    NOTIFICATION_PROVIDER: str = "signal"

    # Telegram (used when NOTIFICATION_PROVIDER=telegram).
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Signal (used when NOTIFICATION_PROVIDER=signal). Backend reaches the
    # local signal-gateway over the shared `signal` docker network.
    SIGNAL_NOTIFY_URL: str = "http://signal-gateway-notify:8090/notify"
    SIGNAL_NOTIFY_TOKEN: str = ""
    SIGNAL_ROUTER_URL: str = "http://signal-gateway-router:8091"
    SIGNAL_ROUTER_TOKEN: str = ""
    SIGNAL_PREFIX: str = "bv"

    LOG_LEVEL: str = "INFO"
    FRONTEND_URL: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
