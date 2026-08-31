#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import math
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import swisseph as swe
from astropy.coordinates import GeocentricTrueEcliptic, get_sun
from astropy.time import Time

ASTRO_CASES = [
    ("ASTRO-01", "1975-04-05T01:30:00+00:00"),
    ("ASTRO-02", "2024-02-04T08:00:00+00:00"),
    ("ASTRO-03", "2024-03-20T03:00:00+00:00"),
    ("ASTRO-04", "2024-04-04T07:00:00+00:00"),
    ("ASTRO-05", "2024-05-05T00:00:00+00:00"),
    ("ASTRO-06", "2024-06-20T20:00:00+00:00"),
    ("ASTRO-07", "2024-07-06T14:00:00+00:00"),
    ("ASTRO-08", "2024-08-07T01:00:00+00:00"),
    ("ASTRO-09", "2024-09-22T12:00:00+00:00"),
    ("ASTRO-10", "2024-10-08T01:00:00+00:00"),
    ("ASTRO-11", "2024-11-07T04:00:00+00:00"),
    ("ASTRO-12", "2024-12-21T09:00:00+00:00"),
]

TZ_CASES = [
    ("TZ-KR-1975-SELF", "1975-04-05", "10:30", "Asia/Seoul", "UNAMBIGUOUS"),
    ("TZ-US-DST-GAP", "2024-03-10", "02:30", "America/New_York", "FAIL_CLOSED_NONEXISTENT"),
    ("TZ-US-DST-FOLD", "2024-11-03", "01:30", "America/New_York", "FAIL_CLOSED_AMBIGUOUS"),
    ("TZ-KR-HISTORICAL-GAP", "1961-08-10", "00:15", "Asia/Seoul", "FAIL_CLOSED_IF_NONEXISTENT_OR_AMBIGUOUS"),
    ("TZ-KR-HISTORICAL-AFTER", "1961-08-10", "00:45", "Asia/Seoul", "UNAMBIGUOUS_IF_TZDB_RESOLVES"),
]

THRESHOLD_DEG = 0.1


def angular_diff(a: float, b: float) -> float:
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def swiss_lon(utc: dt.datetime) -> float:
    h = utc.hour + utc.minute / 60.0 + utc.second / 3600.0 + utc.microsecond / 3_600_000_000.0
    jd = swe.julday(utc.year, utc.month, utc.day, h, swe.GREG_CAL)
    xx, _ = swe.calc_ut(jd, swe.SUN, swe.FLG_SWIEPH)
    return float(xx[0] % 360.0)


def astropy_lon(utc: dt.datetime) -> float:
    t = Time(utc)
    sun = get_sun(t)
    ecl = sun.transform_to(GeocentricTrueEcliptic(equinox=t))
    return float(ecl.lon.deg % 360.0)


def term_index(lon: float) -> int:
    return int(math.floor(((lon - 315.0) % 360.0) / 15.0)) % 24


def local_to_utc(date_text: str, time_text: str, timezone_name: str):
    zone = ZoneInfo(timezone_name)
    naive = dt.datetime.fromisoformat(f"{date_text}T{time_text}")
    candidates = []
    for fold in (0, 1):
        local = naive.replace(tzinfo=zone, fold=fold)
        utc = local.astimezone(dt.timezone.utc)
        back = utc.astimezone(zone).replace(tzinfo=None)
        if back == naive:
            candidates.append((utc, local.utcoffset(), fold))
    unique = {c[0].isoformat(): c for c in candidates}
    if not unique:
        raise RuntimeError("ABSTAIN_TIMEZONE_NONEXISTENT_LOCAL_TIME")
    if len(unique) > 1:
        raise RuntimeError("ABSTAIN_TIMEZONE_AMBIGUOUS_LOCAL_TIME")
    return next(iter(unique.values()))


def run_tz_case(case):
    cid, date_text, time_text, timezone_name, expected = case
    try:
        utc, offset, fold = local_to_utc(date_text, time_text, timezone_name)
        observed = "UNAMBIGUOUS"
        error = None
        utc_text = utc.isoformat()
        offset_seconds = int(offset.total_seconds()) if offset is not None else None
    except RuntimeError as exc:
        error = str(exc)
        utc_text = None
        offset_seconds = None
        fold = None
        if "NONEXISTENT" in error:
            observed = "FAIL_CLOSED_NONEXISTENT"
        elif "AMBIGUOUS" in error:
            observed = "FAIL_CLOSED_AMBIGUOUS"
        else:
            observed = "FAIL_CLOSED_OTHER"
    if expected == "UNAMBIGUOUS":
        passed = observed == "UNAMBIGUOUS"
    elif expected == "UNAMBIGUOUS_IF_TZDB_RESOLVES":
        passed = observed == "UNAMBIGUOUS"
    elif expected == "FAIL_CLOSED_NONEXISTENT":
        passed = observed == "FAIL_CLOSED_NONEXISTENT"
    elif expected == "FAIL_CLOSED_AMBIGUOUS":
        passed = observed == "FAIL_CLOSED_AMBIGUOUS"
    elif expected == "FAIL_CLOSED_IF_NONEXISTENT_OR_AMBIGUOUS":
        passed = observed in {"FAIL_CLOSED_NONEXISTENT", "FAIL_CLOSED_AMBIGUOUS"}
    else:
        passed = False
    return {
        "id": cid,
        "expected_policy": expected,
        "observed": observed,
        "passed": passed,
        "utc": utc_text,
        "offset_seconds": offset_seconds,
        "fold": fold,
        "error": error,
    }


def nominatim_hamyang():
    params = {
        "q": "경상남도 함양군, 대한민국",
        "format": "jsonv2",
        "limit": "5",
        "addressdetails": "1",
        "accept-language": "ko",
        "countrycodes": "kr",
    }
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "NCOS-independent-validation/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if not data:
        return {"passed": False, "error": "NO_CANDIDATE"}
    first = data[0]
    return {
        "passed": True,
        "display_name": first.get("display_name"),
        "lat": first.get("lat"),
        "lon": first.get("lon"),
        "osm_type": first.get("osm_type"),
        "osm_id": first.get("osm_id"),
        "place_id": first.get("place_id"),
        "type": first.get("type"),
        "class": first.get("class"),
        "address": first.get("address"),
    }


def main():
    astro = []
    for cid, utc_text in ASTRO_CASES:
        utc = dt.datetime.fromisoformat(utc_text).astimezone(dt.timezone.utc)
        s = swiss_lon(utc)
        a = astropy_lon(utc)
        diff = angular_diff(s, a)
        si = term_index(s)
        ai = term_index(a)
        astro.append({
            "id": cid,
            "utc": utc.isoformat(),
            "swiss_longitude_deg": round(s, 9),
            "astropy_longitude_deg": round(a, 9),
            "abs_angular_difference_deg": round(diff, 9),
            "swiss_term_index": si,
            "astropy_term_index": ai,
            "longitude_gate_pass": diff <= THRESHOLD_DEG,
            "term_index_gate_pass": si == ai,
        })
    max_diff = max(x["abs_angular_difference_deg"] for x in astro)
    term_rate = sum(1 for x in astro if x["term_index_gate_pass"]) / len(astro)
    astro_pass = all(x["longitude_gate_pass"] for x in astro) and term_rate == 1.0

    tz = [run_tz_case(x) for x in TZ_CASES]
    tz_pass = all(x["passed"] for x in tz)
    self_utc_pass = next(x for x in tz if x["id"] == "TZ-KR-1975-SELF")["utc"].startswith("1975-04-05T01:30:00") if tz_pass else False

    try:
        geo = nominatim_hamyang()
    except Exception as exc:
        geo = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}

    out = {
        "schema_version": "NCOS_INDEPENDENT_PUBLIC_BOUNDARY_VERIFIER_V1",
        "status": "PASS" if astro_pass and tz_pass and self_utc_pass and geo.get("passed") else "FAIL",
        "astronomy": {
            "primary_engine": "SWISS_EPHEMERIS",
            "independent_engine": "ASTROPY_GET_SUN_GEOCENTRIC_TRUE_ECLIPTIC",
            "threshold_deg": THRESHOLD_DEG,
            "case_count": len(astro),
            "max_abs_angular_difference_deg": max_diff,
            "term_index_agreement_rate": term_rate,
            "passed": astro_pass,
            "cases": astro,
        },
        "timezone": {"passed": tz_pass and self_utc_pass, "cases": tz},
        "geocoding": geo,
        "firewall": {
            "biography_used": False,
            "outcome_used": False,
            "research_direction_scorer_called": False,
            "final_holdout_used": False,
            "promotion_scope": "INDEPENDENT_VALIDATION_ONLY",
        },
    }
    with open("validation_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({
        "status": out["status"],
        "astronomy_pass": astro_pass,
        "max_diff_deg": max_diff,
        "term_index_agreement_rate": term_rate,
        "timezone_pass": tz_pass,
        "self_utc_pass": self_utc_pass,
        "geocode_pass": geo.get("passed", False),
        "geocode_display_name": geo.get("display_name"),
        "geocode_lat": geo.get("lat"),
        "geocode_lon": geo.get("lon"),
        "geocode_osm_type": geo.get("osm_type"),
        "geocode_osm_id": geo.get("osm_id"),
    }, ensure_ascii=False))
    if out["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
