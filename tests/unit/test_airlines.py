from pipeline.reference.airlines import get_airline


def test_known_gulf_carrier_prefixes_resolve():
    assert get_airline("UAE85") == "Emirates"
    assert get_airline("QTR123") == "Qatar Airways"
    assert get_airline("SVA555") == "Saudia"
    assert get_airline("ETD60K") == "Etihad Airways"


def test_known_international_carrier_prefixes_resolve():
    assert get_airline("PIA430") == "Pakistan International"
    assert get_airline("IGO057") == "IndiGo"


def test_unrecognized_prefix_is_other_not_dropped():
    assert get_airline("ZZZ999") == "Other"


def test_blank_or_none_callsign_is_unknown_private():
    assert get_airline(None) == "Unknown / private"
    assert get_airline("") == "Unknown / private"
    assert get_airline("   ") == "Unknown / private"
