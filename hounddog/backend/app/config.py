from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://quarry:quarry@localhost:5432/quarry"
    cors_origins: list[str] = ["http://localhost:5173"]
    api_key_header: str = "Authorization"
    secret_key: str = ""
    debug: bool = False

    # Instance identity (used in QR pairing payload)
    public_url: str = "http://localhost:8000"
    school_name: str = ""

    # Okta SSO (Phase 2)
    okta_domain: str = ""
    okta_client_id: str = ""
    okta_client_secret: str = ""
    okta_audience: str = ""

    # Okta role mapping
    admin_okta_groups: str = "Quarry-Admin"
    staff_okta_groups: str = "Quarry-Staff"
    okta_claim: str = "groups"

    # Google Maps
    google_maps_api_key: str = ""
    campus_lat: float = 40.6265
    campus_lng: float = -75.3707

    # Stripe (Phase 3)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""

    # SMTP Email
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""
    smtp_from_name: str = "Quarry Parking"
    smtp_use_tls: bool = True
    lot_closure_mailing_list: str = ""
    citation_from_address: str = ""

    # Twilio SMS
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # Microsoft Teams
    teams_webhook_url: str = ""

    # Zoom Phone
    zoom_account_id: str = ""
    zoom_client_id: str = ""
    zoom_client_secret: str = ""
    zoom_paging_group_id: str = ""

    # Crestron (TBD)
    crestron_host: str = ""
    crestron_api_key: str = ""

    # PA System (TBD)
    pa_system_host: str = ""

    # APNs (Push Notifications)
    apns_key_path: str = ""
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_bundle_id: str = "edu.moravian.birddog"
    apns_use_sandbox: bool = True

    model_config = {"env_prefix": "QUARRY_", "env_file": ".env"}


settings = Settings()
