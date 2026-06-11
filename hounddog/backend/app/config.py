from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://hounddog:hounddog@localhost:5432/hounddog"
    cors_origins: list[str] = ["http://localhost:5173"]
    api_key_header: str = "Authorization"
    secret_key: str = "change-me-in-production"
    debug: bool = False

    # Okta SSO (Phase 2)
    okta_domain: str = ""
    okta_client_id: str = ""
    okta_client_secret: str = ""
    okta_audience: str = ""

    # Stripe (Phase 3)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""

    model_config = {"env_prefix": "HOUNDDOG_", "env_file": ".env"}


settings = Settings()
