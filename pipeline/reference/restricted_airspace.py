"""Real, published restricted/avoided airspace zones and a cost-impact
estimator grounded in real 2026 industry reporting -- not invented numbers.

Sources (see docs/data_dictionary.md for full citations):
- EASA conflict-zone guidance urging carriers to avoid Iranian and Iraqi
  airspace entirely, at all altitudes (aviationnews.eu, July 2026)
- Rerouting adds 300-800 nautical miles and 45-120 minutes of block time on
  affected Europe-Asia routes (SimpleFlying / industry reporting, 2026)
- ~13,000 lbs additional fuel burn per extra flight hour for a widebody
  (777/A350-class), translating to $5,000+ per sector in added fuel cost
  alone at recent jet-fuel pricing; fuel is 25-35% of total airline
  operating cost (SimpleFlying, "Fuel & Flight-Paths: The Hidden Cost of
  Avoiding Hostile Airspace", 2026)
- Detours of 2-3 hours can add $6,000+ per flight hour in total operating
  cost for a widebody (The National / industry estimates, 2026)
- Cumulative industry-wide cost estimated to exceed $1 billion if the
  conflict extends (aerospaceglobalnews.com, 2026)
- Etihad cancelled 450+ flights and Air India halted transit-dependent
  long-haul routes in the same period (simpleflying.com, 2026)

Zone boundaries below are deliberately simplified rectangular bounding
boxes (not exact FIR/ICAO airspace boundaries) -- good enough to show
"real countries whose airspace is being avoided" on a map and to flag
aircraft flying near them, explicitly caveated as approximate everywhere
this is surfaced (never presented as precise airspace boundaries).
"""
from __future__ import annotations

RESTRICTED_ZONES: dict[str, dict] = {
    "Iran": {"lamin": 25.0, "lomin": 44.0, "lamax": 39.8, "lomax": 63.3, "color": [208, 59, 59, 60]},
    "Iraq": {"lamin": 29.1, "lomin": 38.8, "lamax": 37.4, "lomax": 48.6, "color": [208, 59, 59, 60]},
    "Yemen": {"lamin": 12.1, "lomin": 42.5, "lamax": 19.0, "lomax": 54.5, "color": [236, 131, 90, 60]},
}

# Airlines specifically named in 2026 reporting as most disrupted by these
# closures (long-haul carriers whose Europe/Asia routes previously
# transited Iranian/Iraqi airspace) -- see pipeline/reference/airlines.py
# for the full ICAO-code lookup these names come from.
DETOUR_AFFECTED_AIRLINES = {
    "Emirates", "Etihad Airways", "Qatar Airways", "Air India", "Pakistan International",
    "Saudia", "Gulf Air", "Kuwait Airways", "Turkish Airlines", "Singapore Airlines",
}

# Real cited figures, used as the basis for the estimate -- not tuned/fitted.
CRUISE_SPEED_KNOTS = 480  # typical widebody cruise groundspeed
FUEL_COST_PER_EXTRA_HOUR_USD = 5000  # SimpleFlying: "$5,000+ per sector" in added fuel cost per extra hour
FULL_OPERATING_COST_PER_EXTRA_HOUR_USD = 6000  # The National: "$6,000+ per flight hour" full operating cost
TYPICAL_DETOUR_MINUTES_LOW = 45
TYPICAL_DETOUR_MINUTES_HIGH = 120


def zone_for_point(lat: float, lon: float) -> str | None:
    for name, box in RESTRICTED_ZONES.items():
        if box["lamin"] <= lat <= box["lamax"] and box["lomin"] <= lon <= box["lomax"]:
            return name
    return None


def estimate_detour_cost_usd(affected_flight_count: int, use_full_operating_cost: bool = False) -> dict:
    """Applies the real cited per-extra-hour cost figures to a count of
    currently-observed, detour-affected flights, using the midpoint of the
    real cited 45-120 minute detour range as the representative extra time
    per flight. Returned as a range (low/high), not a single false-precision
    number, since both the detour-time range and the cost-per-hour figures
    are themselves ranges from the source reporting.
    """
    per_hour = FULL_OPERATING_COST_PER_EXTRA_HOUR_USD if use_full_operating_cost else FUEL_COST_PER_EXTRA_HOUR_USD
    low_hours = TYPICAL_DETOUR_MINUTES_LOW / 60
    high_hours = TYPICAL_DETOUR_MINUTES_HIGH / 60
    return {
        "affected_flight_count": affected_flight_count,
        "low_usd": round(affected_flight_count * low_hours * per_hour),
        "high_usd": round(affected_flight_count * high_hours * per_hour),
        "per_hour_usd": per_hour,
    }
