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
    okta_class_year_claim: str = "class_year"

    # Google Maps
    google_maps_api_key: str = ""
    google_maps_static_key: str = ""
    campus_lat: float = 40.6265
    campus_lng: float = -75.3707

    # Google Gemini (AI vision for spot detection)
    gemini_api_key: str = ""

    # Stripe (Phase 3)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""

    # Oracle ERP GL Configuration
    gl_ledger: str = "Moravian Primary Ledger"
    gl_source: str = "QUARRY"
    gl_category_revenue: str = "Revenue"
    gl_fund: str = "1110000"
    gl_org: str = "3006"
    gl_account_permits: str = "43002"
    gl_account_citations: str = "43008"
    gl_activity_permits: str = "1068"
    gl_activity_citations: str = "1069"
    gl_activity_zero: str = "0000"
    gl_segment5: str = "0000000"
    gl_segment6: str = "00000"
    gl_account_net_cash: str = "10005"
    gl_org_net_cash: str = "0000"
    gl_account_stripe_fees: str = "60164"
    gl_segment_separator: str = "-"

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

    # Extron Room Agent (scheduling panel override)
    extron_room_agent_url: str = ""

    # Q-SYS (PA/Siren via QRC TCP protocol)
    qsys_core_host: str = ""
    qsys_core_port: int = 1710
    qsys_core_username: str = ""
    qsys_core_password: str = ""

    # APNs (Push Notifications)
    apns_key_path: str = ""
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_bundle_id: str = "edu.moravian.birddog"
    apns_use_sandbox: bool = True

    model_config = {"env_prefix": "QUARRY_", "env_file": ".env"}


settings = Settings()
