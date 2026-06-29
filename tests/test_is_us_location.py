"""Regression tests for find_and_scrape_jobs.is_us_location() - the
2026-06-29 word-boundary fix.

Real incident: is_us_location() used plain substring checks (`term in
loc_lower`), not word-boundary-aware. This caused two classes of bugs,
both confirmed live against real Supabase data before the fix:
  - Real US cities wrongly rejected because a short negative_indicators
    term matched as a substring inside the city name: "uk" inside
    "Milwaukee"/"Tukwila".
  - Real non-US locations wrongly accepted because a short us_cities
    abbreviation matched as a substring inside an unrelated word: "la"
    (Los Angeles) inside "England".
"""
import find_and_scrape_jobs as f


def test_substring_false_rejections_now_fixed():
    # "uk" is a substring of these real US city names - previously caused
    # is_us_location() to incorrectly return False.
    assert f.is_us_location("Milwaukee, WI (Remote/Hybrid)") is True
    assert f.is_us_location("Tukwila, WA") is True
    assert f.is_us_location("Indianapolis, IN, United States (Remote/Hybrid)") is True


def test_substring_false_acceptances_now_fixed():
    # "la" (Los Angeles abbreviation) is a substring of "England" -
    # previously caused is_us_location() to incorrectly return True.
    assert f.is_us_location("Manchester, England (Remote)") is False
    assert f.is_us_location("Wakefield, England, United Kingdom (Hybrid)") is False


def test_explicit_us_state_wins_over_foreign_capital_name_collision():
    # "Vienna" collides with negative_indicators (Vienna, Austria), and
    # similarly "Paris"/"Berlin"/"Athens"/"Cairo"/"Rome"/"Milan"/"Dublin"
    # are all real US town names too. Explicit US evidence (a state
    # abbreviation, full state name, or "United States") must win over an
    # ambiguous city-name collision, not get vetoed by it.
    assert f.is_us_location("Vienna, VA, United States (Remote/Hybrid)") is True
    assert f.is_us_location("Vienna, Austria") is False


def test_genuine_us_locations_still_accepted():
    for loc in [
        "Remote",
        "San Mateo, CA (Remote/Hybrid)",
        "Austin, TX",
        "Augusta, GA",
        "Las Vegas, NV",
        "Lahaina, HI",
        "New York, NY, United States",
    ]:
        assert f.is_us_location(loc) is True, loc


def test_genuine_non_us_locations_still_rejected():
    for loc in [
        "Bangalore, India (Remote/Hybrid)",
        "Mexico City, Mexico (Remote/Hybrid)",
        "Nuremberg, Germany",
        "Toronto, Ontario, Canada",
    ]:
        assert f.is_us_location(loc) is False, loc
