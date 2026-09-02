from __future__ import annotations

import math
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sgp4.api import Satrec, WGS72, jday
from sgp4 import exporter

EARTH_RADIUS_KM = 6378.137
MU_EARTH = 398600.4418  # km^3/s^2, standard gravitational parameter


# --------------------------------------------------------------------------
# Sample catalog
# --------------------------------------------------------------------------
# A small, hand-picked set of real-world-format TLEs covering a mix of
# operational statuses so risk scoring has something meaningful to chew on.
# (Orbital elements are representative/illustrative for a prototype, not
# guaranteed to be the live current TLE for each object.)

SAMPLE_CATALOG = [
    {
        "norad_id": "25544",
        "name": "ISS (ZARYA)",
        "line1": "1 25544U 98067A   26236.54200000  .00016717  00000-0  10270-3 0  9008",
        "line2": "2 25544  51.6412  22.9760 0003821  49.8021  60.0912 15.50003725 12345",
        "status": "active",
        "operator": "NASA/Roscosmos",
        "population_served": 7,           # crew on board
        "replacement_cost_usd": 150_000_000_000,
        "object_type": "station",
    },
    {
        "norad_id": "48274",
        "name": "STARLINK-2000",
        "line1": "1 48274U 21044A   26235.50000000  .00002182  00000-0  16538-3 0  9995",
        "line2": "2 48274  53.0534 190.3421 0001321  95.1234 265.0021 15.06400000123456",
        "status": "active",
        "operator": "SpaceX",
        "population_served": 50_000,       # est. users served by this node
        "replacement_cost_usd": 500_000,
        "object_type": "communications",
    },
    {
        "norad_id": "33591",
        "name": "NOAA-19",
        "line1": "1 33591U 09005A   26234.47000000  .00000123  00000-0  87654-4 0  9994",
        "line2": "2 33591  99.0450 250.1234 0013567 120.0000 240.1234 14.12345678123456",
        "status": "active",
        "operator": "NOAA",
        "population_served": 2_000_000,    # weather-forecast beneficiaries (approx.)
        "replacement_cost_usd": 220_000_000,
        "object_type": "weather",
    },
    {
        "norad_id": "39084",
        "name": "COSMOS 2251 DEB",
        "line1": "1 39084U 93036SX  26237.60000000  .00000045  00000-0  10000-3 0  9991",
        "line2": "2 39084  74.0400 100.0000 0021000  10.0000 350.0000 14.30000000123456",
        "status": "debris",
        "operator": "N/A",
        "population_served": 0,
        "replacement_cost_usd": 0,
        "object_type": "debris",
    },
    {
        "norad_id": "27424",
        "name": "ENVISAT (DEFUNCT)",
        "line1": "1 27424U 02009A   26233.55000000  .00000067  00000-0  20000-4 0  9992",
        "line2": "2 27424  98.2000 150.0000 0001200  90.0000 270.0000 14.37000000123456",
        "status": "inactive",
        "operator": "ESA",
        "population_served": 0,
        "replacement_cost_usd": 1_100_000_000,
        "object_type": "earth_observation",
    },
    {
        # Deliberately near-co-orbital with the ISS (tiny mean-anomaly offset)
        # so the demo has an out-of-the-box close approach to analyze.
        "norad_id": "90001",
        "name": "DEBRIS FRAGMENT (DEMO)",
        "line1": "1 90001U 98067C   26236.54200000  .00016717  00000-0  10270-3 0  9002",
        "line2": "2 90001  51.6412  22.9760 0003821  49.8021  60.1250 15.50003725 12341",
        "status": "debris",
        "operator": "N/A",
        "population_served": 0,
        "replacement_cost_usd": 0,
        "object_type": "debris",
    },
]


@dataclass
class SatelliteRecord:
    norad_id: str
    name: str
    line1: str
    line2: str
    status: str
    operator: str
    population_served: int
    replacement_cost_usd: float
    object_type: str
    satrec: Satrec = field(repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "norad_id": self.norad_id,
            "name": self.name,
            "status": self.status,
            "operator": self.operator,
            "population_served": self.population_served,
            "replacement_cost_usd": self.replacement_cost_usd,
            "object_type": self.object_type,
            "tle": {"line1": self.line1, "line2": self.line2},
            "orbit_summary": orbital_elements_summary(self.satrec),
        }


class Catalog:
    """In-memory satellite catalog keyed by NORAD id."""

    def __init__(self, records: Optional[list] = None):
        self._by_id: dict[str, SatelliteRecord] = {}
        for entry in records or SAMPLE_CATALOG:
            self.add_from_tle(**entry)

    def add_from_tle(self, norad_id, name, line1, line2, status="unknown",
                      operator="unknown", population_served=0,
                      replacement_cost_usd=0.0, object_type="unknown"):
        satrec = Satrec.twoline2rv(line1, line2)
        rec = SatelliteRecord(
            norad_id=str(norad_id), name=name, line1=line1, line2=line2,
            status=status, operator=operator,
            population_served=population_served,
            replacement_cost_usd=replacement_cost_usd,
            object_type=object_type, satrec=satrec,
        )
        self._by_id[rec.norad_id] = rec
        return rec

    def get(self, norad_id: str) -> Optional[SatelliteRecord]:
        return self._by_id.get(str(norad_id))

    def all(self) -> list[SatelliteRecord]:
        return list(self._by_id.values())

    def clear(self):
        """Empty the catalog. Needed because Catalog(records=[]) would
        actually fall back to SAMPLE_CATALOG — an empty list is falsy,
        so `records or SAMPLE_CATALOG` silently ignores it."""
        self._by_id = {}

    def search(self, query: str) -> list[SatelliteRecord]:
        q = query.strip().lower()
        if not q:
            return self.all()
        return [
            r for r in self._by_id.values()
            if q in r.name.lower() or q in r.norad_id.lower() or q in r.operator.lower()
        ]

    def list_dicts(self) -> list[dict]:
        return [r.to_dict() for r in self.all()]


# --------------------------------------------------------------------------
# Propagation helpers
# --------------------------------------------------------------------------

def _datetime_to_jd_fr(dt: datetime):
    dt = dt.astimezone(timezone.utc)
    jd, fr = jday(dt.year, dt.month, dt.day, dt.hour, dt.minute,
                   dt.second + dt.microsecond / 1e6)
    return jd, fr


def propagate_eci(satrec: Satrec, dt: datetime):
    """Return (position_km[3], velocity_km_s[3]) in TEME/ECI at time dt."""
    jd, fr = _datetime_to_jd_fr(dt)
    error_code, position, velocity = satrec.sgp4(jd, fr)
    if error_code != 0:
        raise RuntimeError(f"SGP4 propagation error code {error_code} at {dt.isoformat()}")
    return position, velocity


def eci_to_geodetic(position_km, dt: datetime):
    """Very lightweight spherical-Earth ECI(TEME)->lat/lon/alt conversion.

    Good enough for visualization purposes in a prototype (a few km of
    lat/lon error vs. a full WGS84 + sidereal-time model is acceptable here).
    """
    x, y, z = position_km
    r = math.sqrt(x * x + y * y + z * z)
    lat = math.degrees(math.asin(z / r))

    # Greenwich Mean Sidereal Time (approx, IAU 1982 simplified formula)
    jd, fr = _datetime_to_jd_fr(dt)
    jd_full = jd + fr
    T = (jd_full - 2451545.0) / 36525.0
    gmst_deg = (280.46061837 + 360.98564736629 * (jd_full - 2451545.0)
                + 0.000387933 * T * T) % 360.0

    lon_eci = math.degrees(math.atan2(y, x))
    lon = (lon_eci - gmst_deg + 180) % 360 - 180
    alt = r - EARTH_RADIUS_KM
    return {"lat": lat, "lon": lon, "alt_km": alt}


def propagate_track(satrec: Satrec, start: datetime, end: datetime, step_seconds: float):
    """Return a list of {time, position_km, velocity_km_s, lat, lon, alt_km}."""
    track = []
    t = start
    while t <= end:
        pos, vel = propagate_eci(satrec, t)
        geo = eci_to_geodetic(pos, t)
        track.append({
            "time": t.isoformat(),
            "position_km": list(pos),
            "velocity_km_s": list(vel),
            **geo,
        })
        t += timedelta(seconds=step_seconds)
    return track


def orbital_elements_summary(satrec: Satrec) -> dict:
    """Rough Keplerian summary derived from the mean-motion / eccentricity
    stored in the TLE, useful for display and for ML features."""
    n_rad_s = satrec.no_kozai / 60.0  # rad/min -> rad/s
    a_km = (MU_EARTH / (n_rad_s ** 2)) ** (1.0 / 3.0)
    e = satrec.ecco
    i_deg = math.degrees(satrec.inclo)
    perigee_alt = a_km * (1 - e) - EARTH_RADIUS_KM
    apogee_alt = a_km * (1 + e) - EARTH_RADIUS_KM
    period_min = (2 * math.pi / n_rad_s) / 60.0
    return {
        "semi_major_axis_km": round(a_km, 2),
        "eccentricity": round(e, 6),
        "inclination_deg": round(i_deg, 3),
        "perigee_alt_km": round(perigee_alt, 2),
        "apogee_alt_km": round(apogee_alt, 2),
        "period_min": round(period_min, 2),
        "epoch_days": satrec.jdsatepoch + satrec.jdsatepochF,
    }


def tle_age_days(satrec: Satrec, at: datetime) -> float:
    jd, fr = _datetime_to_jd_fr(at)
    epoch = satrec.jdsatepoch + satrec.jdsatepochF
    return (jd + fr) - epoch


def satrec_from_lines(line1: str, line2: str) -> Satrec:
    return Satrec.twoline2rv(line1, line2)


# --------------------------------------------------------------------------
# Live CelesTrak catalog (real satellites, not the 6 hardcoded demo objects)
# --------------------------------------------------------------------------
# CelesTrak (celestrak.org) is a free, public source of current TLE data —
# no API key or account required. This lets the search bar find real,
# currently-orbiting satellites instead of only the illustrative sample
# catalog above. If the fetch fails for any reason (no internet, CelesTrak
# unreachable, blocked network), everything falls back to SAMPLE_CATALOG
# so the app still runs.

CELESTRAK_GROUP_URLS = {
    "stations": "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle",
    "active": "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle",
    "starlink": "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle",
    "weather": "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle",
    "gps-ops": "https://celestrak.org/NORAD/elements/gp.php?GROUP=gps-ops&FORMAT=tle",
}


def fetch_celestrak_tle_text(url: str, timeout: float = 10.0) -> str:
    """Fetch raw TLE text from a CelesTrak group URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "OrbitSentinel/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def parse_tle_text(text: str) -> list[dict]:
    """Parse CelesTrak's 3-line-per-satellite TLE text format into a list
    of {"norad_id", "name", "line1", "line2"} dicts."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    records = []
    i = 0
    while i + 2 < len(lines):
        name, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
        if l1.startswith("1 ") and l2.startswith("2 "):
            norad_id = l1[2:7].strip()
            records.append({
                "norad_id": norad_id,
                "name": name.strip(),
                "line1": l1,
                "line2": l2,
            })
            i += 3
        else:
            # Not a clean triplet (stray/blank line) — skip forward one
            # line at a time until we find the next valid pattern.
            i += 1
    return records


def fetch_celestrak_catalog(groups=("stations", "active"), max_per_group: int = 40) -> list[dict]:
    """Fetch and parse several CelesTrak groups into catalog-ready dicts.

    CelesTrak doesn't provide operational metadata (operator, population
    served, replacement cost), so those are filled with honest generic
    defaults — real values would need to come from a separate source.
    """
    object_type_by_group = {
        "stations": "station",
        "active": "satellite",
        "starlink": "communications",
        "weather": "weather",
        "gps-ops": "navigation",
    }

    all_records = []
    for group in groups:
        url = CELESTRAK_GROUP_URLS.get(group)
        if not url:
            continue
        text = fetch_celestrak_tle_text(url)  # let exceptions propagate to caller
        parsed = parse_tle_text(text)[:max_per_group]
        object_type = object_type_by_group.get(group, "satellite")
        for rec in parsed:
            rec.update({
                "status": "active",
                "operator": "Unknown (live CelesTrak data)",
                "population_served": 0,
                "replacement_cost_usd": 0,
                "object_type": object_type,
            })
        all_records.extend(parsed)
    return all_records


def build_live_catalog(groups=("stations", "active"), max_per_group: int = 40,
                        fallback_to_sample: bool = True, include_demo_debris: bool = True) -> "Catalog":
    """Build a Catalog from live CelesTrak data.

    Always tries to include the synthetic near-ISS demo debris object
    (NORAD 90001) alongside real data, so there's a guaranteed close
    approach to demo regardless of what real satellites happen to be
    doing right now. Falls back to the small static SAMPLE_CATALOG if the
    live fetch fails for any reason (no internet, CelesTrak down, etc.).
    """
    cat = Catalog()
    cat.clear()

    try:
        live_records = fetch_celestrak_catalog(groups=groups, max_per_group=max_per_group)
        if not live_records:
            raise RuntimeError("CelesTrak returned no usable records")

        for rec in live_records:
            try:
                cat.add_from_tle(**rec)
            except Exception:
                # Skip any single malformed TLE rather than failing the
                # whole catalog load over one bad entry.
                continue

        if include_demo_debris:
            demo_entry = next(e for e in SAMPLE_CATALOG if e["norad_id"] == "90001")
            cat.add_from_tle(**demo_entry)

        print(f"[OrbitSentinel] Loaded {len(cat.all())} satellites from live CelesTrak data.")

    except Exception as exc:
        if not fallback_to_sample:
            raise
        print(f"[OrbitSentinel] Live TLE fetch failed ({exc!r}); using bundled sample catalog instead.")
        cat = Catalog()  # the original 6-object static sample catalog

    return cat
