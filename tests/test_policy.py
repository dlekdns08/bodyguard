from datetime import datetime

from bodyguard.policy import Thresholds, evaluate, explain, in_late_window, load_thresholds
from bodyguard.vitals import Vitals

NOON = datetime(2026, 1, 1, 12, 0)
LATE = datetime(2026, 1, 1, 1, 15)

GOOD = dict(body_battery=85, sleep_score=82, stress_avg=25, hrv_status="BALANCED")


def test_high_when_everything_is_good():
    d = evaluate(Vitals(**GOOD), now=NOON)
    assert d.level == "HIGH"
    assert any("Body Battery 85" in r for r in d.reasons)


def test_normal_when_no_data():
    d = evaluate(Vitals(), now=NOON)
    assert d.level == "NORMAL"
    assert d.reasons == ["no vitals available"]


def test_unknown_sleep_never_grants_high():
    d = evaluate(Vitals(body_battery=90, stress_avg=10), now=NOON)
    assert d.level == "NORMAL"


def test_low_body_battery():
    d = evaluate(Vitals(**{**GOOD, "body_battery": 18}), now=NOON)
    assert d.level == "LOW"
    assert "Body Battery 18 < 25" in d.reasons


def test_low_sleep_score():
    d = evaluate(Vitals(**{**GOOD, "sleep_score": 41}), now=NOON)
    assert d.level == "LOW"
    assert "sleep score 41 < 50" in d.reasons


def test_low_hrv_status():
    d = evaluate(Vitals(**{**GOOD, "hrv_status": "low"}), now=NOON)
    assert d.level == "LOW"
    assert "HRV status LOW" in d.reasons


def test_low_stress():
    d = evaluate(Vitals(**{**GOOD, "stress_avg": 80}), now=NOON)
    assert d.level == "LOW"


def test_unbalanced_hrv_is_normal_not_low():
    d = evaluate(Vitals(**{**GOOD, "hrv_status": "UNBALANCED"}), now=NOON)
    assert d.level == "NORMAL"


def test_rest_late_and_stressed():
    d = evaluate(Vitals(**{**GOOD, "stress_avg": 60}), now=LATE)
    assert d.level == "REST"
    assert "01:15" in d.reasons[0]


def test_late_but_calm_is_not_rest():
    d = evaluate(Vitals(**GOOD), now=LATE)
    assert d.level == "HIGH"


def test_rest_on_empty_battery_any_time():
    d = evaluate(Vitals(body_battery=5), now=NOON)
    assert d.level == "REST"


def test_rest_wins_over_low():
    d = evaluate(Vitals(body_battery=5, sleep_score=30), now=NOON)
    assert d.level == "REST"


def test_late_window_wraps_midnight():
    t = Thresholds(rest_after="23:00", rest_until="05:00")
    assert in_late_window(datetime(2026, 1, 1, 23, 30), t)
    assert in_late_window(datetime(2026, 1, 1, 2, 0), t)
    assert not in_late_window(datetime(2026, 1, 1, 12, 0), t)


def test_custom_thresholds():
    t = Thresholds(low_body_battery=40)
    assert evaluate(Vitals(**{**GOOD, "body_battery": 35}), t, now=NOON).level == "LOW"


def test_load_thresholds_from_toml(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[thresholds]\nlow_body_battery = 40\nrest_after = "23:00"\nlow_hrv_statuses = ["low", "unbalanced"]\n'
    )
    t = load_thresholds(cfg)
    assert t.low_body_battery == 40
    assert t.rest_after == "23:00"
    assert t.low_hrv_statuses == ("LOW", "UNBALANCED")
    assert t.high_body_battery == 70  # default kept


def test_load_thresholds_missing_or_broken(tmp_path):
    assert load_thresholds(tmp_path / "nope.toml") == Thresholds()
    bad = tmp_path / "bad.toml"
    bad.write_text("this is = not [ toml")
    assert load_thresholds(bad) == Thresholds()


def test_explain_mentions_level_and_thresholds():
    text = explain(Vitals(body_battery=18), now=NOON)
    assert "autonomy: LOW" in text
    assert "low_body_battery = 25" in text
