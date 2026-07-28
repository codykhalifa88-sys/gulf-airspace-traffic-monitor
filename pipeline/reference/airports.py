"""Gulf airport reference data and nearest-region assignment. Pure
functions, no I/O -- directly unit-testable."""
from __future__ import annotations

import math

from pipeline.config import AIRPORTS, NEAREST_REGION_MAX_KM

_EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def assign_nearest_region(lat: float, lon: float) -> str:
    """Nearest of the 8 Gulf airport centroids. Beyond NEAREST_REGION_MAX_KM
    from all of them, returns "OTHER" -- real, interesting open-Gulf
    overflight/transit traffic, not force-attributed to a distant airport
    that isn't actually relevant to it.
    """
    nearest_code, nearest_km = None, float("inf")
    for code, (airport_lat, airport_lon) in AIRPORTS.items():
        km = haversine_km(lat, lon, airport_lat, airport_lon)
        if km < nearest_km:
            nearest_code, nearest_km = code, km
    if nearest_km > NEAREST_REGION_MAX_KM:
        return "OTHER"
    return nearest_code
