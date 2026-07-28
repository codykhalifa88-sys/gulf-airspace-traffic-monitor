from pipeline.reference.airports import assign_nearest_region, haversine_km


def test_haversine_matches_real_dxb_auh_distance():
    # Real-world DXB-AUH great-circle distance is ~115-120km; computed here
    # from the actual airport coordinates in pipeline/config.py, not a
    # hardcoded assumption -- this pins the calculation, not the airports.
    km = haversine_km(25.2532, 55.3657, 24.4330, 54.6511)
    assert 110 < km < 125


def test_point_at_an_airport_resolves_to_that_airport():
    assert assign_nearest_region(25.2532, 55.3657) == "DXB"
    assert assign_nearest_region(25.2731, 51.6081) == "DOH"


def test_point_far_from_every_airport_is_other():
    assert assign_nearest_region(15.0, 55.0) == "OTHER"


def test_point_near_but_not_at_an_airport_resolves_to_nearest():
    # A small offset east of DXB, still clearly closer to DXB than to any
    # other airport (nearest alternative, AUH, is ~116km further west).
    assert assign_nearest_region(25.30, 55.90) == "DXB"
