"""Map vitals to an autonomy level. Pure functions, no I/O except ``load_thresholds``.

Levels, from most to least autonomous:

* ``HIGH``   - well rested, low stress: Claude may take bigger steps.
* ``NORMAL`` - default Claude Code behaviour.
* ``LOW``    - running low: risky commands require confirmation.
* ``REST``   - late and stressed, or nearly empty: every write asks, Claude suggests stopping.

Every decision carries human-readable reasons so the hook can tell the user
*why* it is asking, e.g. "Body Battery 18 < 25".
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any

from .vitals import Vitals

LEVELS = ("HIGH", "NORMAL", "LOW", "REST")

LEVEL_INSTRUCTION = {
    "HIGH": (
        "The user is well rested (vitals look good). You may take larger, more "
        "autonomous steps; still confirm before destructive or irreversible actions."
    ),
    "NORMAL": "The user's vitals are normal. Behave as usual.",
    "LOW": (
        "The user is running low on energy. Prefer smaller steps, summarise before "
        "acting, and confirm before anything irreversible (force pushes, deletes, "
        "deploys, migrations). Keep answers short."
    ),
    "REST": (
        "The user should probably stop for today. Avoid new large tasks: suggest "
        "wrapping up, committing work-in-progress and resting. Every write or shell "
        "command will ask for confirmation. Keep answers very short."
    ),
}


@dataclass
class Thresholds:
    """All tunables, overridable from ``~/.config/bodyguard/config.toml``."""

    # LOW triggers (any one is enough)
    low_body_battery: int = 25
    low_sleep_score: int = 50
    low_stress_avg: int = 75
    low_hrv_statuses: tuple[str, ...] = ("LOW",)

    # REST triggers
    rest_body_battery: int = 10
    rest_after: str = "00:30"      # local time, HH:MM
    rest_until: str = "05:00"      # the late-night window ends here
    rest_stress_avg: int = 50      # "stress high" inside the window

    # HIGH requirements (all must hold; unknown values never grant HIGH)
    high_body_battery: int = 70
    high_sleep_score: int = 70
    high_stress_avg: int = 40
    high_hrv_statuses: tuple[str, ...] = ("BALANCED",)

    # Hook behaviour
    cache_ttl_seconds: int = 15 * 60
    block_risky_at_low: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Thresholds":
        known = {f.name: f for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known:
                continue
            if isinstance(value, list):
                value = tuple(str(x).upper() for x in value)
            kwargs[key] = value
        return cls(**kwargs)


def config_path() -> Path:
    env = os.environ.get("BODYGUARD_CONFIG")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "bodyguard" / "config.toml"


def load_thresholds(path: Path | None = None) -> Thresholds:
    """Read the TOML config; missing or broken files fall back to defaults."""
    path = path or config_path()
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return Thresholds()
    section = data.get("thresholds", data)
    if not isinstance(section, dict):
        return Thresholds()
    try:
        return Thresholds.from_dict(section)
    except TypeError:
        return Thresholds()


@dataclass
class Decision:
    level: str
    reasons: list[str] = field(default_factory=list)
    vitals: Vitals | None = None

    @property
    def instruction(self) -> str:
        return LEVEL_INSTRUCTION[self.level]

    def summary(self) -> str:
        why = "; ".join(self.reasons) if self.reasons else "no triggers"
        return f"autonomy {self.level} ({why})"


def _parse_hhmm(value: str) -> dtime:
    try:
        h, m = value.split(":")
        return dtime(int(h), int(m))
    except (ValueError, AttributeError):
        return dtime(0, 30)


def in_late_window(now: datetime, t: Thresholds) -> bool:
    """True when local time is inside [rest_after, rest_until). Handles midnight wrap."""
    start, end = _parse_hhmm(t.rest_after), _parse_hhmm(t.rest_until)
    cur = now.time()
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end


def evaluate(v: Vitals, t: Thresholds | None = None, now: datetime | None = None) -> Decision:
    """The policy. Deterministic given (vitals, thresholds, now)."""
    t = t or Thresholds()
    now = now or datetime.now()
    hrv = (v.hrv_status or "").upper() or None

    # --- REST ---------------------------------------------------------------
    rest: list[str] = []
    if v.body_battery is not None and v.body_battery < t.rest_body_battery:
        rest.append(f"Body Battery {v.body_battery} < {t.rest_body_battery}")
    if in_late_window(now, t) and v.stress_avg is not None and v.stress_avg >= t.rest_stress_avg:
        rest.append(
            f"it is {now.strftime('%H:%M')} (after {t.rest_after}) and avg stress "
            f"{v.stress_avg} >= {t.rest_stress_avg}"
        )
    if rest:
        return Decision("REST", rest, v)

    # --- LOW ----------------------------------------------------------------
    low: list[str] = []
    if v.body_battery is not None and v.body_battery < t.low_body_battery:
        low.append(f"Body Battery {v.body_battery} < {t.low_body_battery}")
    if v.sleep_score is not None and v.sleep_score < t.low_sleep_score:
        low.append(f"sleep score {v.sleep_score} < {t.low_sleep_score}")
    if hrv in t.low_hrv_statuses:
        low.append(f"HRV status {hrv}")
    if v.stress_avg is not None and v.stress_avg >= t.low_stress_avg:
        low.append(f"avg stress {v.stress_avg} >= {t.low_stress_avg}")
    if low:
        return Decision("LOW", low, v)

    # --- HIGH ---------------------------------------------------------------
    if (
        v.body_battery is not None
        and v.body_battery >= t.high_body_battery
        and v.sleep_score is not None
        and v.sleep_score >= t.high_sleep_score
        and (v.stress_avg is None or v.stress_avg <= t.high_stress_avg)
        and (hrv is None or hrv in t.high_hrv_statuses)
    ):
        high = [
            f"Body Battery {v.body_battery} >= {t.high_body_battery}",
            f"sleep score {v.sleep_score} >= {t.high_sleep_score}",
        ]
        if v.stress_avg is not None:
            high.append(f"avg stress {v.stress_avg} <= {t.high_stress_avg}")
        if hrv:
            high.append(f"HRV {hrv}")
        return Decision("HIGH", high, v)

    # --- NORMAL -------------------------------------------------------------
    if v.is_empty():
        return Decision("NORMAL", ["no vitals available"], v)
    return Decision("NORMAL", ["no thresholds crossed"], v)


def explain(v: Vitals, t: Thresholds | None = None, now: datetime | None = None) -> str:
    """Multi-line explanation used by ``bodyguard policy --explain``."""
    t = t or Thresholds()
    d = evaluate(v, t, now)
    lines = [f"autonomy: {d.level}", "", "reasons:"]
    lines += [f"  - {r}" for r in d.reasons]
    lines += ["", "thresholds:"]
    for f in fields(t):
        lines.append(f"  {f.name} = {getattr(t, f.name)!r}")
    return "\n".join(lines)
