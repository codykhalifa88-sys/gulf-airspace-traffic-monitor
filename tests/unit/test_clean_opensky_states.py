import json

from pipeline.ingest.opensky_states import states_to_records

with open("tests/fixtures/opensky_states_gulf_sample.json") as f:
    REAL_RESPONSE = json.load(f)


def test_real_fixture_produces_expected_shape():
    records = states_to_records(REAL_RESPONSE)
    assert len(records) == len(REAL_RESPONSE["states"])
    assert set(records[0].keys()) == {
        "icao24",
        "callsign",
        "origin_country",
        "longitude",
        "latitude",
        "baro_altitude",
        "on_ground",
        "velocity",
        "true_track",
        "vertical_rate",
        "geo_altitude",
        "poll_timestamp",
    }


def test_poll_timestamp_comes_from_top_level_time():
    records = states_to_records(REAL_RESPONSE)
    assert all(r["poll_timestamp"] == REAL_RESPONSE["time"] for r in records)


def test_callsign_is_stripped_and_blank_becomes_none():
    response = {"time": 1, "states": [["abc123", "SIA123  ", "Singapore", None, None, 1.0, 2.0, 3.0, False, 4.0, 5.0, 6.0, None, 7.0, None, False, 0]]}
    records = states_to_records(response)
    assert records[0]["callsign"] == "SIA123"

    response_blank = {"time": 1, "states": [["abc123", "        ", "Singapore", None, None, 1.0, 2.0, 3.0, False, 4.0, 5.0, 6.0, None, 7.0, None, False, 0]]}
    records_blank = states_to_records(response_blank)
    assert records_blank[0]["callsign"] is None


def test_row_with_null_icao24_is_dropped():
    response = {"time": 1, "states": [[None, "X", "Y", None, None, 1.0, 2.0, 3.0, False, 4.0, 5.0, 6.0, None, 7.0, None, False, 0]]}
    assert states_to_records(response) == []


def test_empty_states_list_produces_no_records():
    assert states_to_records({"time": 1, "states": []}) == []
    assert states_to_records({"time": 1, "states": None}) == []
