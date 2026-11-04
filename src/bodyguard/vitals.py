"""Fetch wearable vitals (Garmin) with a small on-disk cache.

Hooks run on every tool call, so they must be fast. The rule is simple:
never talk to Garmin on the hot path. ``get_vitals()`` returns the cached
snapshot immediately; when it is older than the TTL it kicks off a detached
background refresh and returns the stale snapshot for now.

Everything is nullable. A watch that was not worn, a day without sleep data,
or an expired token all degrade to ``None`` fields, never to an exception.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_TTL_SECONDS = 15 * 60
"""How long a cached snapshot is considered fresh."""

MAX_STALE_SECONDS = 6 * 60 * 60
"""Beyond this age a cached snapshot is ignored entirely."""


@dataclass
class Vitals:
    """A snapshot of the wearer's state. All metrics are optional."""

    body_battery: int | None = None
    stress_avg: int | None = None
    stress_max: int | None = None
    sleep_score: int | None = None
    sleep_hours: float | None = None
    hrv_status: str | None = None
    hrv_last_night: int | None = None
    hrv_weekly_avg: int | None = None
    fetched_at: float = field(default_factory=time.time)
    source: str = "none"
    day: str | None = None
    error: str | None = None

    def age_seconds(self, now: float | None = None) -> float:
        return max(0.0, (now or time.time()) - self.fetched_at)

    def is_empty(self) -> bool:
        return all(
            getattr(self, f.name) is None
            for f in fields(self)
            if f.name not in {"fetched_at", "source", "day", "error"}
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Vitals":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #


def cache_path() -> Path:
    env = os.environ.get("BODYGUARD_CACHE")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "bodyguard" / "vitals.json"


def token_dir() -> str:
    return os.environ.get("GARMINTOKENS", os.path.expanduser("~/.garminconnect"))


# --------------------------------------------------------------------------- #
# Parsing helpers (defensive: Garmin payloads vary by device and day)
# --------------------------------------------------------------------------- #


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return None if v < 0 else v


def parse_body_battery(payload: Any) -> int | None:
    """``get_body_battery(day)`` -> ``[{"bodyBatteryValuesArray": [[epoch_ms, value], ...]}]``."""
    try:
        values = payload[0]["bodyBatteryValuesArray"] or []
        for item in reversed(values):
            if item and len(item) >= 2 and item[1] is not None:
                return _as_int(item[1])
    except (IndexError, KeyError, TypeError):
        pass
    return None


def parse_stress(payload: Any) -> tuple[int | None, int | None]:
    """``get_stress_data(day)`` -> ``{"avgStressLevel": .., "maxStressLevel": ..}``."""
    if not isinstance(payload, dict):
        return None, None
    return _as_int(payload.get("avgStressLevel")), _as_int(payload.get("maxStressLevel"))


def parse_sleep(payload: Any) -> tuple[int | None, float | None]:
    """``get_sleep_data(day)["dailySleepDTO"]`` -> score + hours."""
    try:
        dto = payload["dailySleepDTO"] or {}
    except (KeyError, TypeError):
        return None, None
    score = None
    try:
        score = _as_int(dto["sleepScores"]["overall"]["value"])
    except (KeyError, TypeError):
        pass
    seconds = _as_int(dto.get("sleepTimeSeconds"))
    hours = round(seconds / 3600, 1) if seconds else None
    return score, hours


def parse_hrv(payload: Any) -> tuple[str | None, int | None, int | None]:
    """``get_hrv_data(day)["hrvSummary"]`` -> status, lastNightAvg, weeklyAvg."""
    try:
        summary = payload["hrvSummary"] or {}
    except (KeyError, TypeError):
        return None, None, None
    status = summary.get("status")
    status = str(status).upper() if status else None
    return status, _as_int(summary.get("lastNightAvg")), _as_int(summary.get("weeklyAvg"))


# --------------------------------------------------------------------------- #
# Garmin adapter
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def _quiet():
    """The garminconnect library logs noisily to stderr/stdout. Hooks must stay silent."""
    with open(os.devnull, "w") as devnull:
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = devnull, devnull
        try:
            yield
        finally:
            sys.stdout, sys.stderr = old_out, old_err


def fetch_from_garmin(day: str | None = None) -> Vitals:
    """Hit Garmin Connect (read-only) and build a fresh snapshot."""
    from garminconnect import Garmin  # imported lazily: keeps tests and --help fast

    day = day or date.today().isoformat()
    v = Vitals(source="garmin", day=day)
    with _quiet():
        client = Garmin()
        client.login(token_dir())

        def call(name: str):
            try:
                return getattr(client, name)(day)
            except Exception:  # noqa: BLE001 - one missing metric must not sink the rest
                return None

        v.body_battery = parse_body_battery(call("get_body_battery"))
        v.stress_avg, v.stress_max = parse_stress(call("get_stress_data"))
        v.sleep_score, v.sleep_hours = parse_sleep(call("get_sleep_data"))
        v.hrv_status, v.hrv_last_night, v.hrv_weekly_avg = parse_hrv(call("get_hrv_data"))
    v.fetched_at = time.time()
    return v


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #


def read_cache(path: Path | None = None) -> Vitals | None:
    path = path or cache_path()
    try:
        data = json.loads(path.read_text())
        v = Vitals.from_dict(data)
        v.source = "cache"
        return v
    except (OSError, ValueError, TypeError):
        return None


def write_cache(v: Vitals, path: Path | None = None) -> None:
    path = path or cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(v.to_dict(), indent=2))
        os.replace(tmp, path)
    except OSError:
        pass


def fake_from_env() -> Vitals | None:
    """``BODYGUARD_FAKE='{"body_battery": 18}'`` bypasses the watch entirely."""
    raw = os.environ.get("BODYGUARD_FAKE")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return Vitals(source="fake", error="BODYGUARD_FAKE is not valid JSON")
    v = Vitals.from_dict(data if isinstance(data, dict) else {})
    v.source = "fake"
    v.fetched_at = time.time()
    return v


def refresh(path: Path | None = None) -> Vitals:
    """Fetch now (blocking) and update the cache. Returns the snapshot, possibly with ``error``."""
    try:
        v = fetch_from_garmin()
    except Exception as exc:  # noqa: BLE001
        stale = read_cache(path)
        if stale is not None:
            stale.error = f"refresh failed: {type(exc).__name__}"
            return stale
        return Vitals(source="none", error=f"{type(exc).__name__}: {exc}"[:200])
    write_cache(v, path)
    return v


def _spawn_background_refresh() -> None:
    """Refresh without blocking the caller. Best effort; silent on failure."""
    if os.environ.get("BODYGUARD_NO_BACKGROUND"):
        return
    try:
        subprocess.Popen(
            [sys.executable, "-m", "bodyguard.cli", "refresh", "--quiet"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def get_vitals(
    ttl: int = DEFAULT_TTL_SECONDS,
    *,
    force: bool = False,
    block: bool = False,
    path: Path | None = None,
) -> Vitals:
    """Return the best available snapshot.

    Resolution order:

    1. ``BODYGUARD_FAKE`` env var (tests, demos, people without a watch)
    2. a cache entry younger than ``ttl``
    3. a stale cache entry (younger than ``MAX_STALE_SECONDS``), plus a background refresh
    4. a blocking fetch when ``block`` is set or when there is nothing cached
    """
    fake = fake_from_env()
    if fake is not None:
        return fake

    cached = None if force else read_cache(path)
    if cached is not None:
        age = cached.age_seconds()
        if age <= ttl:
            return cached
        if age <= MAX_STALE_SECONDS and not block:
            _spawn_background_refresh()
            return cached

    return refresh(path)
