"""Tests for the salary/location/company normalization modules."""
from company_normalizer import normalize_company
from location_normalizer import normalize_location
from salary_normalizer import normalize_salary


def test_location_normalizes_city_state_variants_to_same_display():
    a = normalize_location("Austin TX")
    b = normalize_location("Austin, Texas")
    c = normalize_location("Austin, TX")
    assert a["display"] == b["display"] == c["display"] == "Austin, TX, USA"
    assert not a["is_remote"] and not a["is_hybrid"]


def test_location_detects_remote():
    r = normalize_location("Remote")
    assert r["display"] == "Remote"
    assert r["is_remote"] is True
    assert r["is_hybrid"] is False


def test_location_detects_remote_with_city_suffix():
    r = normalize_location("Austin, TX (Remote)")
    assert r["is_remote"] is True
    assert "Austin, TX, USA" in r["display"]


def test_location_detects_hybrid():
    r = normalize_location("Hybrid - Dallas, TX")
    assert r["is_hybrid"] is True
    assert r["is_remote"] is False
    assert "Dallas, TX, USA" in r["display"]


def test_location_falls_back_to_cleaned_text_for_unparseable_input():
    r = normalize_location("London, UK")
    assert r["display"] == "London, UK"
    assert not r["is_remote"]


def test_company_normalizes_known_alias():
    assert normalize_company("BofA") == "Bank of America"
    assert normalize_company("Bank of America Corp") == "Bank of America"
    assert normalize_company("Bank of America") == "Bank of America"


def test_company_strips_legal_suffix_generically():
    assert normalize_company("Acme Inc.") == "Acme"
    assert normalize_company("Acme Corporation") == "Acme"


def test_company_empty_string_returns_empty():
    assert normalize_company("") == ""


def test_salary_extracts_yearly_range():
    result = normalize_salary("We pay $120,000 - $180,000 per year plus bonus.", "Engineer")
    assert result["salary_min"] == 120000.0
    assert result["salary_max"] == 180000.0
    assert result["pay_period"] == "year"
    assert result["currency"] == "USD"


def test_salary_extracts_hourly_rate():
    result = normalize_salary("Contract rate: $45 - $65 / hour", "Contractor")
    assert result["pay_period"] == "hour"
    assert result["salary_min"] == 45.0
    assert result["salary_max"] == 65.0


def test_salary_returns_none_fields_when_no_signal():
    result = normalize_salary("No salary mentioned here.", "Engineer")
    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert result["currency"] == "USD"
    assert result["pay_period"] == "year"
