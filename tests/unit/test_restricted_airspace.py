from pipeline.reference.restricted_airspace import estimate_detour_cost_usd, zone_for_point


def test_point_inside_iran_is_flagged():
    assert zone_for_point(32.0, 53.0) == "Iran"


def test_point_inside_yemen_is_flagged():
    assert zone_for_point(15.5, 47.5) == "Yemen"


def test_point_over_jeddah_is_not_flagged():
    # Jeddah (21.68, 39.16) is well clear of all three simplified bounding
    # boxes (Iran's southern edge is lat 25.0, Yemen's northern edge is
    # lat 19.0) -- unlike a central-Gulf point, which the Iran box's real
    # coastline-driven rectangle legitimately does cover (an accepted
    # limitation of simplified boxes, documented in the module docstring).
    assert zone_for_point(21.68, 39.16) is None


def test_cost_estimate_scales_linearly_with_flight_count():
    zero = estimate_detour_cost_usd(0)
    ten = estimate_detour_cost_usd(10)
    assert zero["low_usd"] == 0
    assert ten["low_usd"] == 10 * zero["per_hour_usd"] * (45 / 60)
    assert ten["high_usd"] == 10 * zero["per_hour_usd"] * (120 / 60)
    assert ten["low_usd"] < ten["high_usd"]


def test_full_operating_cost_is_higher_than_fuel_only():
    fuel_only = estimate_detour_cost_usd(5, use_full_operating_cost=False)
    full_cost = estimate_detour_cost_usd(5, use_full_operating_cost=True)
    assert full_cost["low_usd"] > fuel_only["low_usd"]
