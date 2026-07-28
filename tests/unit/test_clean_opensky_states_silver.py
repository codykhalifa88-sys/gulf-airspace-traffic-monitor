from pipeline.transform.silver import clean_opensky_states


def _record(icao24="abc123", callsign="UAE85", lat=25.2532, lon=55.3657):
    return {
        "icao24": icao24,
        "callsign": callsign,
        "origin_country": "United Arab Emirates",
        "longitude": lon,
        "latitude": lat,
        "baro_altitude": 10000.0,
        "velocity": 230.0,
        "true_track": 90.0,
        "vertical_rate": 0.0,
        "on_ground": False,
        "poll_timestamp": 1700000000,
    }


def test_airline_is_resolved_from_callsign():
    out = clean_opensky_states([_record(callsign="UAE85")])
    assert out.iloc[0]["airline"] == "Emirates"


def test_nearest_region_and_airline_both_present_in_output_columns():
    out = clean_opensky_states([_record()])
    assert list(out.columns) == [
        "icao24",
        "callsign",
        "airline",
        "origin_country",
        "longitude",
        "latitude",
        "baro_altitude",
        "velocity",
        "true_track",
        "vertical_rate",
        "on_ground",
        "poll_timestamp",
        "nearest_region",
    ]
    assert out.iloc[0]["nearest_region"] == "DXB"


def test_empty_input_has_airline_column_too():
    out = clean_opensky_states([])
    assert "airline" in out.columns
    assert len(out) == 0
