from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine.url import URL, make_url

from gst_automation.core.exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class DbTarget:
    drivername: str
    username: str | None
    host: str | None
    port: int | None
    database: str | None

    @property
    def display(self) -> str:
        # Sanitized (no password)
        host = self.host or ""
        port = str(self.port) if self.port else ""
        db = self.database or ""
        user = self.username or ""
        return f"{self.drivername}://{user}@{host}:{port}/{db}"


def parse_db_url(url: str) -> tuple[URL, DbTarget]:
    try:
        u = make_url(url)
    except Exception as exc:  # noqa: BLE001
        raise ConfigurationError(f"Invalid DATABASE_URL: {exc}") from exc

    target = DbTarget(
        drivername=str(u.drivername),
        username=str(u.username) if u.username else None,
        host=str(u.host) if u.host else None,
        port=int(u.port) if u.port else None,
        database=str(u.database) if u.database else None,
    )
    return u, target


def validate_db_url(url: str, *, label: str) -> DbTarget:
    _u, target = parse_db_url(url)

    if not target.drivername.startswith("postgresql"):
        raise ConfigurationError(f"{label}: unsupported driver '{target.drivername}' (expected postgresql)")
    if target.drivername not in {"postgresql+asyncpg", "postgresql+psycopg"}:
        raise ConfigurationError(
            f"{label}: invalid driver '{target.drivername}' (expected postgresql+asyncpg or postgresql+psycopg)"
        )
    if not target.host:
        raise ConfigurationError(f"{label}: missing host")
    if not target.port:
        raise ConfigurationError(f"{label}: missing port")
    if not target.database:
        raise ConfigurationError(f"{label}: missing database name")
    if not target.username:
        raise ConfigurationError(f"{label}: missing username")
    # Password must be present for deterministic local ops (docker compose init uses it).
    if not _u.password:
        raise ConfigurationError(f"{label}: missing password")
    return target
