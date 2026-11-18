"""Application settings, read from environment variables (or a local .env file).

No secret is stored in the source code: copy `.env.example` to `.env` and fill it in.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

try:  # python-dotenv is optional at runtime (Docker passes env vars directly)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


class ConfigError(RuntimeError):
    """Raised when a required setting is missing."""


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    odoo_url: str
    odoo_db: str
    odoo_user: str
    odoo_password: str
    odoo_verify_ssl: bool = True
    odoo_timeout: float = 30.0
    timezone: str = "Europe/Zurich"
    cors_origins: tuple[str, ...] = ("*",)


@lru_cache
def get_settings() -> Settings:
    missing = [name for name in ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_PASSWORD") if not os.getenv(name)]
    if missing:
        raise ConfigError(f"Missing environment variable(s): {', '.join(missing)} (see .env.example)")
    origins = tuple(o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()) or ("*",)
    return Settings(
        odoo_url=os.environ["ODOO_URL"].rstrip("/"),
        odoo_db=os.environ["ODOO_DB"],
        odoo_user=os.environ["ODOO_USER"],
        odoo_password=os.environ["ODOO_PASSWORD"],
        odoo_verify_ssl=_bool(os.getenv("ODOO_VERIFY_SSL", "true")),
        odoo_timeout=float(os.getenv("ODOO_TIMEOUT", "30")),
        timezone=os.getenv("APP_TIMEZONE", "Europe/Zurich"),
        cors_origins=origins,
    )
