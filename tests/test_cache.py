"""Cache TTL and parsing. Garmin is never contacted: the fetcher is monkeypatched."""

import time

import pytest

from bodyguard import vitals as vt
from bodyguard.vitals import Vitals, get_vitals, read_cache, write_cache


@pytest.fixture
def no_garmin(monkeypatch):
    calls = []

    def fake_fetch(day=None):
        calls.append(day)
        return Vitals(body_battery=55, source="garmin", fetched_at=time.time())

    monkeypatch.setattr(vt, "fetch_from_garmin", fake_fetch)
    return calls


def test_fake_env_wins(isolated_env, monkeypatch, no_garmin):
    monkeypatch.setenv("BODYGUARD_FAKE", '{"body_battery": 18, "hrv_status": "LOW"}')
    v = get_vitals()
    assert v.source == "fake"
    assert v.body_battery == 18
    assert no_garmin == []


def test_fetches_when_cache_missing(isolated_env, no_garmin):
    v = get_vitals()
    assert v.body_battery == 55
    assert len(no_garmin) == 1
    assert read_cache().body_battery == 55


def test_fresh_cache_skips_fetch(isolated_env, no_garmin):
    write_cache(Vitals(body_battery=40, fetched_at=time.time() - 60))
    v = get_vitals(ttl=900)
    assert v.body_battery == 40
    assert v.source == "cache"
    assert no_garmin == []


def test_stale_cache_is_returned_immediately(isolated_env, no_garmin):
    write_cache(Vitals(body_battery=40, fetched_at=time.time() - 20 * 60))
    v = get_vitals(ttl=900)  # background refresh disabled by fixture
    assert v.body_battery == 40
    assert no_garmin == []


def test_stale_cache_blocking_refetches(isolated_env, no_garmin):
    write_cache(Vitals(body_battery=40, fetched_at=time.time() - 20 * 60))
    v = get_vitals(ttl=900, block=True)
    assert v.body_battery == 55
    assert len(no_garmin) == 1


def test_very_old_cache_is_ignored(isolated_env, no_garmin):
    write_cache(Vitals(body_battery=40, fetched_at=time.time() - 24 * 3600))
    v = get_vitals(ttl=900)
    assert v.body_battery == 55


def test_force_bypasses_cache(isolated_env, no_garmin):
    write_cache(Vitals(body_battery=40))
    assert get_vitals(force=True).body_battery == 55


def test_fetch_failure_falls_back_to_stale_cache(isolated_env, monkeypatch):
    def boom(day=None):
        raise RuntimeError("token expired")

    monkeypatch.setattr(vt, "fetch_from_garmin", boom)
    write_cache(Vitals(body_battery=40, fetched_at=time.time() - 20 * 60))
    v = get_vitals(ttl=900, block=True)
    assert v.body_battery == 40
    assert "refresh failed" in v.error


def test_fetch_failure_without_cache_is_empty_not_exception(isolated_env, monkeypatch):
    monkeypatch.setattr(vt, "fetch_from_garmin", lambda day=None: (_ for _ in ()).throw(RuntimeError("x")))
    v = get_vitals()
    assert v.is_empty()
    assert v.error


def test_corrupt_cache_is_ignored(isolated_env, no_garmin):
    vt.cache_path().parent.mkdir(parents=True, exist_ok=True)
    vt.cache_path().write_text("{{{")
    assert get_vitals().body_battery == 55


# ---- parsers against synthetic Garmin shapes -------------------------------


def test_parse_body_battery_takes_last_value():
    payload = [{"bodyBatteryValuesArray": [[1, 80], [2, 61], [3, None], [4, 37]]}]
    assert vt.parse_body_battery(payload) == 37
    assert vt.parse_body_battery([]) is None
    assert vt.parse_body_battery([{"bodyBatteryValuesArray": []}]) is None


def test_parse_stress_handles_minus_one():
    assert vt.parse_stress({"avgStressLevel": -1, "maxStressLevel": None}) == (None, None)
    assert vt.parse_stress({"avgStressLevel": 42, "maxStressLevel": 91}) == (42, 91)
    assert vt.parse_stress(None) == (None, None)


def test_parse_sleep():
    payload = {"dailySleepDTO": {"sleepTimeSeconds": 25200, "sleepScores": {"overall": {"value": 71}}}}
    assert vt.parse_sleep(payload) == (71, 7.0)
    assert vt.parse_sleep({"dailySleepDTO": {}}) == (None, None)
    assert vt.parse_sleep({}) == (None, None)


def test_parse_hrv():
    payload = {"hrvSummary": {"lastNightAvg": 38, "weeklyAvg": 45, "status": "low"}}
    assert vt.parse_hrv(payload) == ("LOW", 38, 45)
    assert vt.parse_hrv({"hrvSummary": None}) == (None, None, None)
