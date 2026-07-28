"""ICAO callsign-prefix -> airline lookup. Real, documented ICAO airline
designators (the 3-letter prefix on a callsign, e.g. "UAE85" -> Emirates),
covering the Gulf carriers plus the major international carriers actually
seen flying through this bounding box during development (India, Pakistan,
Russia, Malta, US origin countries all showed up in real captured data)."""
from __future__ import annotations

import re

ICAO_AIRLINE_CODES: dict[str, str] = {
    # Gulf carriers
    "UAE": "Emirates",
    "ETD": "Etihad Airways",
    "QTR": "Qatar Airways",
    "SVA": "Saudia",
    "GFA": "Gulf Air",
    "KAC": "Kuwait Airways",
    "OMA": "Oman Air",
    "FDB": "flydubai",
    "ABY": "Air Arabia",
    "XY": "flynas",
    "MSC": "Air Cairo",
    # Major international carriers seen in this corridor
    "PIA": "Pakistan International",
    "AIC": "Air India",
    "IGO": "IndiGo",
    "SIA": "Singapore Airlines",
    "THY": "Turkish Airlines",
    "MSR": "EgyptAir",
    "RJA": "Royal Jordanian",
    "MEA": "Middle East Airlines",
    "UAL": "United Airlines",
    "AAL": "American Airlines",
    "DAL": "Delta Air Lines",
    "BAW": "British Airways",
    "DLH": "Lufthansa",
    "AFR": "Air France",
    "KLM": "KLM",
    "AFL": "Aeroflot",
    "ANA": "All Nippon Airways",
    "JAL": "Japan Airlines",
    "CCA": "Air China",
    "CPA": "Cathay Pacific",
    "UPS": "UPS Airlines",
    "FDX": "FedEx Express",
    "CKS": "Kalitta Air",
}

_PREFIX_RE = re.compile(r"^[A-Z]{2,3}")

# Fixed categorical color assignment (dataviz skill: "assign categorical
# hues in fixed order, never cycled" -- an airline always gets the same
# color regardless of rank/filter state). Validated default palette, slots
# 1-8 in order: blue, orange, aqua, yellow, magenta, green, violet, red.
# The live map (an all-pairs context: many points visible simultaneously)
# uses only the first 3 slots per the skill's all-pairs cap; the ranked
# bar chart (adjacent-pairs only) can safely use all 8.
AIRLINE_CATEGORICAL_ORDER = [
    "Emirates",
    "Etihad Airways",
    "Qatar Airways",
    "Saudia",
    "Air India",
    "Pakistan International",
    "Turkish Airlines",
    "Singapore Airlines",
]
AIRLINE_CATEGORICAL_HEX = [
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
]
AIRLINE_COLOR_HEX: dict[str, str] = dict(zip(AIRLINE_CATEGORICAL_ORDER, AIRLINE_CATEGORICAL_HEX))
OTHER_COLOR_HEX = "#898781"


def get_airline(callsign: str | None) -> str:
    if not callsign:
        return "Unknown / private"
    match = _PREFIX_RE.match(callsign.strip().upper())
    if not match:
        return "Unknown / private"
    return ICAO_AIRLINE_CODES.get(match.group(0), "Other")
