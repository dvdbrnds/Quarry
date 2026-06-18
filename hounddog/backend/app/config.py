from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://quarry:quarry@localhost:5432/quarry"
    cors_origins: list[str] = ["http://localhost:5173"]
    api_key_header: str = "Authorization"
    secret_key: str = "change-me-in-production"
    debug: bool = False

    # Instance identity (used in QR pairing payload)
    public_url: str = "http://localhost:8000"
    school_name: str = ""

    # Okta SSO (Phase 2)
    okta_domain: str = ""
    okta_client_id: str = ""
    okta_client_secret: str = ""
    okta_audience: str = ""

    # Google Maps
    google_maps_api_key: str = ""

    # Stripe (Phase 3)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""

    # APNs (Push Notifications)
    apns_key_path: str = ""
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_bundle_id: str = "edu.moravian.birddog"
    apns_use_sandbox: bool = True

    model_config = {"env_prefix": "QUARRY_", "env_file": ".env"}


settings = Settings()
