from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "Shongkhep API"
    api_v1_prefix: str = "/api/v1"
    auto_create_tables: bool = False

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/shongkhep"
    )
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    cors_origins: list[str] = ["*"]
    rss_feed_urls_en: list[str] = [
        "https://en.prothomalo.com/stories.rss",
        "https://www.thedailystar.net/frontpage/rss.xml",
        "https://www.bd24live.com/feed",
        "https://bdnews24.com/?widgetName=rssfeed&widgetId=1150&getXmlFeed=true",
    ]
    rss_feed_urls_bn: list[str] = [
        "https://www.prothomalo.com/feed",
        "https://www.jagonews24.com/rss/rss.xml",
    ]
    default_page_size: int = 20
    feed_sync_interval_minutes: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
