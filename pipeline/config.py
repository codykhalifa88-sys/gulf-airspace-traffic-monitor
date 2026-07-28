"""Shared config for the pipeline, ingest/transform/serving modules, and the
dashboard. Same env-driven pattern as the sibling ev-charging-gap-analysis
project."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL") or None
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")

ENV_NAME = os.getenv("ENV_NAME", "dev")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", f"gulf-airspace-traffic-monitor-{ENV_NAME}")

KINESIS_STREAM_NAME = os.getenv("KINESIS_STREAM_NAME", f"gulf-airspace-states-{ENV_NAME}")

DYNAMODB_TRAFFIC_TABLE = os.getenv("DYNAMODB_TRAFFIC_TABLE", "gulf_traffic_by_region")
DYNAMODB_CONFLICT_EVENTS_TABLE = os.getenv("DYNAMODB_CONFLICT_EVENTS_TABLE", "gulf_conflict_events")
DYNAMODB_MANIFEST_TABLE = os.getenv("DYNAMODB_MANIFEST_TABLE", "gulf_pipeline_manifest")

# Middle East bounding box (Egypt/Red Sea in the west to Iran in the east,
# Yemen in the south to Iraq/Syria/Lebanon in the north) -- widened from an
# initial Gulf-only box; confirmed live against OpenSky (real aircraft:
# Saudi Arabian Airlines, Etihad, Oman Air, PIA, and traffic further west/
# north once the box was widened).
GULF_BBOX = {"lamin": 12.0, "lomin": 31.0, "lamax": 37.5, "lomax": 63.3}

# 15 major Middle East airports: code -> (lat, lon). Aircraft beyond
# NEAREST_REGION_MAX_KM from all of these are bucketed as "OTHER"
# (overflight/transit traffic). Kept the module-level name AIRPORTS (not
# renamed to e.g. MIDDLE_EAST_AIRPORTS) to avoid a disruptive rename across
# already-provisioned DynamoDB/Terraform resources mid-build.
AIRPORTS = {
    # Gulf / GCC
    "DXB": (25.2532, 55.3657),  # Dubai, UAE
    "DOH": (25.2731, 51.6081),  # Doha, Qatar
    "RUH": (24.9576, 46.6988),  # Riyadh, Saudi Arabia
    "JED": (21.6796, 39.1565),  # Jeddah, Saudi Arabia
    "AUH": (24.4330, 54.6511),  # Abu Dhabi, UAE
    "KWI": (29.2266, 47.9689),  # Kuwait City, Kuwait
    "BAH": (26.2708, 50.6336),  # Manama, Bahrain
    "MCT": (23.5933, 58.2844),  # Muscat, Oman
    # Broader Middle East
    "CAI": (30.1219, 31.4056),  # Cairo, Egypt
    "AMM": (31.7226, 35.9932),  # Amman, Jordan
    "BEY": (33.8209, 35.4884),  # Beirut, Lebanon
    "TLV": (32.0055, 34.8854),  # Tel Aviv, Israel
    "BGW": (33.2625, 44.2346),  # Baghdad, Iraq
    "DAM": (33.4114, 36.5156),  # Damascus, Syria
    "IKA": (35.4161, 51.1522),  # Tehran, Iran
}
NEAREST_REGION_MAX_KM = 150

OPENSKY_BASE_URL = os.getenv("OPENSKY_BASE_URL", "https://opensky-network.org/api")
OPENSKY_AUTH_URL = os.getenv(
    "OPENSKY_AUTH_URL", "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
)
OPENSKY_CLIENT_ID = os.getenv("OPENSKY_CLIENT_ID", "")
OPENSKY_CLIENT_SECRET = os.getenv("OPENSKY_CLIENT_SECRET", "")

GDELT_LASTUPDATE_URL = os.getenv("GDELT_LASTUPDATE_URL", "http://data.gdeltproject.org/gdeltv2/lastupdate.txt")
# QuadClass 1=verbal cooperation, 2=material cooperation, 3=verbal conflict,
# 4=material conflict. >=3 is the conflict-relevance filter for this project.
GDELT_MIN_QUAD_CLASS = int(os.getenv("GDELT_MIN_QUAD_CLASS", "3"))

BUCKET_MINUTES = int(os.getenv("BUCKET_MINUTES", "5"))
ROLLING_BASELINE_MIN_BUCKETS = int(os.getenv("ROLLING_BASELINE_MIN_BUCKETS", "12"))  # 1hr @ 5-min buckets
ROLLING_BASELINE_MAX_BUCKETS = int(os.getenv("ROLLING_BASELINE_MAX_BUCKETS", "288"))  # 24hr ceiling

# Optional, sparse, never on the automated cron -- see docs/data_dictionary.md
AVIATIONSTACK_API_KEY = os.getenv("AVIATIONSTACK_API_KEY", "")
TRAVELPAYOUTS_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN", "")

LOG_DIR = os.getenv("LOG_DIR", "logs")
