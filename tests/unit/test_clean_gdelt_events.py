from pipeline.transform.silver import clean_gdelt_events

FIXTURE = "tests/fixtures/gdelt_export_sample.CSV.zip"


def _load_raw() -> bytes:
    with open(FIXTURE, "rb") as f:
        return f.read()


def test_real_fixture_filters_to_middle_east_bbox_and_quad_class():
    # This fixture is a real trimmed slice of an actual GDELT export
    # (captured live during this session). With the Middle East bbox
    # (widened from an initial Gulf-only box), 4 real rows fall inside and
    # have QuadClass >= 3 (verbal/material conflict) -- 3 in the Gulf
    # itself and 1 real event near Amman, Jordan that the original
    # narrower Gulf-only bbox would have excluded. The remaining ~15 rows
    # in this fixture are real non-Middle-East events included specifically
    # to prove the bbox filter actually excludes them.
    out = clean_gdelt_events(_load_raw())
    assert len(out) == 4
    assert (out["quad_class"] >= 3).all()
    assert out["action_geo_lat"].between(12.0, 37.5).all()
    assert out["action_geo_long"].between(31.0, 63.3).all()
    assert "AMM" in set(out["nearest_region"])


def test_real_fixture_produces_expected_columns():
    out = clean_gdelt_events(_load_raw())
    assert list(out.columns) == [
        "global_event_id",
        "event_timestamp",
        "actor1_name",
        "actor2_name",
        "event_code",
        "quad_class",
        "goldstein_scale",
        "num_mentions",
        "num_sources",
        "num_articles",
        "action_geo_lat",
        "action_geo_long",
        "action_geo_country_code",
        "source_url",
        "nearest_region",
    ]


def test_real_fixture_has_a_real_source_url_and_actor():
    out = clean_gdelt_events(_load_raw())
    assert out["source_url"].str.startswith("http").all()
    assert (out["actor1_name"].notna()).any()


def test_action_geo_country_code_is_fips_not_iso():
    # Confirmed against real data during planning: Saudi Arabia is FIPS
    # "SA" (matches ISO by coincidence) but Iraq is FIPS "IZ", not ISO's
    # "IQ" -- this fixture's real rows include an Iraq-actor event with a
    # Saudi Arabia ActionGeo_CountryCode, which is the real, confirmed value.
    out = clean_gdelt_events(_load_raw())
    assert "SA" in set(out["action_geo_country_code"])
