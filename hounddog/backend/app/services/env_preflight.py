"""
Production environment variable preflight check.

Validates that all required production env vars are present and sane.
Does NOT print secret values — only presence/format validity.
"""

import logging
import re

from ..config import settings

logger = logging.getLogger("quarry.preflight")

INSECURE_SECRETS = {"", "changeme", "secret", "password", "test", "dev", "CHANGE_ME"}


def _mask(value: str) -> str:
    """Show first 4 chars + masked remainder for display."""
    if not value:
        return "(empty)"
    if len(value) <= 6:
        return "***"
    return value[:4] + "***"


def run_preflight() -> list[dict]:
    """Run all preflight checks. Returns list of check results.

    Each result: {"name": str, "status": "pass"|"fail"|"warn", "detail": str}
    """
    results: list[dict] = []

    def check(name: str, status: str, detail: str):
        results.append({"name": name, "status": status, "detail": detail})

    # --- DATABASE ---
    if not settings.database_url:
        check("DATABASE_URL", "fail", "Not set")
    elif "localhost" in settings.database_url and not settings.debug:
        check("DATABASE_URL", "warn", "Points to localhost in non-debug mode")
    elif "asyncpg" not in settings.database_url:
        check("DATABASE_URL", "fail", "Must use postgresql+asyncpg:// driver")
    else:
        check("DATABASE_URL", "pass", "Set (asyncpg driver)")

    # --- SECRET_KEY ---
    if not settings.secret_key:
        check("SECRET_KEY", "fail", "Not set — sessions/tokens insecure")
    elif settings.secret_key.lower() in INSECURE_SECRETS:
        check("SECRET_KEY", "fail", "Using default/insecure value")
    elif len(settings.secret_key) < 32:
        check("SECRET_KEY", "warn", f"Only {len(settings.secret_key)} chars — recommend 64+")
    else:
        check("SECRET_KEY", "pass", f"{len(settings.secret_key)} chars")

    # --- STRIPE ---
    sk = settings.stripe_secret_key
    if not sk:
        check("STRIPE_SECRET_KEY", "fail", "Not set — payments disabled")
    elif sk.startswith("sk_test_"):
        check("STRIPE_SECRET_KEY", "warn", "Using TEST key — not live")
    elif sk.startswith("sk_live_"):
        check("STRIPE_SECRET_KEY", "pass", "Live key set")
    else:
        check("STRIPE_SECRET_KEY", "warn", f"Unusual prefix: {_mask(sk)}")

    pk = settings.stripe_publishable_key
    if not pk:
        check("STRIPE_PUBLISHABLE_KEY", "warn", "Not set (frontend may need it)")
    elif pk.startswith("pk_test_"):
        check("STRIPE_PUBLISHABLE_KEY", "warn", "Using TEST key")
    else:
        check("STRIPE_PUBLISHABLE_KEY", "pass", "Set")

    # --- SMTP ---
    if not settings.smtp_host:
        check("SMTP_HOST", "fail", "Not set — emails disabled")
    else:
        check("SMTP_HOST", "pass", settings.smtp_host)

    if not settings.smtp_from_address:
        check("SMTP_FROM_ADDRESS", "fail", "Not set")
    else:
        check("SMTP_FROM_ADDRESS", "pass", settings.smtp_from_address)

    if not settings.smtp_user:
        check("SMTP_USER", "warn", "Not set — may fail auth")
    else:
        check("SMTP_USER", "pass", "Set")

    if not settings.smtp_password:
        check("SMTP_PASSWORD", "warn", "Not set — may fail auth")
    else:
        check("SMTP_PASSWORD", "pass", "Set (masked)")

    # --- TWILIO ---
    if not settings.twilio_account_sid:
        check("TWILIO_ACCOUNT_SID", "warn", "Not set — SMS disabled")
    else:
        check("TWILIO_ACCOUNT_SID", "pass", _mask(settings.twilio_account_sid))

    if not settings.twilio_auth_token:
        check("TWILIO_AUTH_TOKEN", "warn", "Not set — SMS disabled")
    else:
        check("TWILIO_AUTH_TOKEN", "pass", "Set (masked)")

    if not settings.twilio_from_number:
        check("TWILIO_FROM_NUMBER", "warn", "Not set — SMS disabled")
    else:
        check("TWILIO_FROM_NUMBER", "pass", settings.twilio_from_number)

    # --- CORS ---
    if not settings.cors_origins:
        check("CORS_ORIGINS", "fail", "Empty — frontend cannot connect")
    elif any("localhost" in o for o in settings.cors_origins) and not settings.debug:
        check("CORS_ORIGINS", "warn", "Contains localhost in non-debug mode")
    else:
        check("CORS_ORIGINS", "pass", f"{len(settings.cors_origins)} origin(s)")

    # --- OKTA ---
    if not settings.okta_domain:
        check("OKTA_DOMAIN", "warn", "Not set — auth disabled (open admin access)")
    else:
        check("OKTA_DOMAIN", "pass", settings.okta_domain)
        if not settings.okta_client_id:
            check("OKTA_CLIENT_ID", "fail", "Domain set but client ID missing")
        else:
            check("OKTA_CLIENT_ID", "pass", "Set")

    # --- Log summary ---
    fails = [r for r in results if r["status"] == "fail"]
    warns = [r for r in results if r["status"] == "warn"]
    passes = [r for r in results if r["status"] == "pass"]

    logger.info("=" * 60)
    logger.info("ENV VAR PREFLIGHT: %d pass, %d warn, %d FAIL", len(passes), len(warns), len(fails))
    logger.info("-" * 60)
    for r in results:
        icon = "✓" if r["status"] == "pass" else "⚠" if r["status"] == "warn" else "✗"
        logger.info("  %s %-24s %s", icon, r["name"], r["detail"])
    logger.info("=" * 60)

    if fails:
        logger.error("PREFLIGHT FAILED: %d critical issues must be resolved", len(fails))

    return results
