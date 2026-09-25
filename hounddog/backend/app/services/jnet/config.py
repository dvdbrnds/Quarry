"""JNET / CJIS configuration — all env vars for the JNET walled garden."""

from pydantic_settings import BaseSettings


class JNETSettings(BaseSettings):
    # Feature flag — off by default
    jnet_enabled: bool = False
    jnet_base_url: str = ""

    # mTLS certificates
    jnet_client_cert_path: str = ""
    jnet_client_key_path: str = ""
    jnet_ca_bundle_path: str = ""

    # Originating Agency Identifier
    jnet_ori: str = ""

    # Timeouts
    jnet_timeout_seconds: int = 15

    # CJIS session
    jnet_session_timeout_minutes: int = 30

    # Anomaly detection
    jnet_shift_start_hour: int = 6
    jnet_shift_end_hour: int = 23
    jnet_allowed_ip_ranges: str = ""
    jnet_max_same_plate_queries_24h: int = 3
    jnet_max_queries_per_minute: int = 10

    # Incident response
    cjis_incident_email: str = ""

    # Access policy
    jnet_inactive_revoke_days: int = 90
    jnet_training_validity_days: int = 365

    model_config = {"env_prefix": "", "env_file": ".env"}


jnet_settings = JNETSettings()
