"""Tests for backend/tools/find_care.py

Strategy: mock all Google Maps API calls so tests run without API keys
or network access. Pure helpers tested directly.

Pure unit tests (no mocks):
  _haversine_miles, _hours_today, _plan_value, _plan_confidence,
  _telehealth_result, _format_result

Integration tests (Google Maps mocked via _get_gmaps_client):
  run_find_care — all care_type paths, fallback scenarios, output structure

Run from backend/:
  python -m pytest tests/test_find_care.py -v
  python tests/test_find_care.py
"""

import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.find_care as fc

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

# Boston, MA — used as user location
USER_LAT = 42.3601
USER_LNG = -71.0589

MOCK_PLAN_JSON = {
    "telehealth_copay":            {"value": "$0",    "confidence": "HIGH", "page": 2, "bbox": None, "source_text": None},
    "telehealth_covered":          {"value": True,    "confidence": "HIGH", "page": 2, "bbox": None, "source_text": None},
    "insurer_provider_finder_url": {"value": "https://example.com/find", "confidence": "HIGH", "page": 3, "bbox": None, "source_text": None},
    "insurer_phone":               {"value": "1-800-555-1234", "confidence": "HIGH", "page": 3, "bbox": None, "source_text": None},
}

# Two fake places — second one farther away than first
MOCK_PLACE_1 = {
    "place_id": "ChIJplace1",
    "name": "City Urgent Care",
    "vicinity": "100 Main St, Boston, MA 02101",
    "geometry": {"location": {"lat": 42.3605, "lng": -71.0592}},  # ~0.03 miles
    "opening_hours": {"open_now": True},
    "rating": 4.5,
    "user_ratings_total": 200,
}
MOCK_PLACE_2 = {
    "place_id": "ChIJplace2",
    "name": "Metro Urgent Care",
    "vicinity": "500 Elm St, Cambridge, MA 02139",
    "geometry": {"location": {"lat": 42.3730, "lng": -71.1190}},  # ~3.5 miles
    "opening_hours": {"open_now": False},
    "rating": 4.2,
    "user_ratings_total": 150,
}

MOCK_PLACES_RESPONSE = {
    "results": [MOCK_PLACE_1, MOCK_PLACE_2],
    "status": "OK",
}

MOCK_PLACE_DETAILS_RESPONSE = {
    "result": {
        "formatted_phone_number": "(617) 555-1234",
        "opening_hours": {
            "weekday_text": [
                "Monday: 8:00 AM – 8:00 PM",
                "Tuesday: 8:00 AM – 8:00 PM",
                "Wednesday: 8:00 AM – 8:00 PM",
                "Thursday: 8:00 AM – 8:00 PM",
                "Friday: 8:00 AM – 8:00 PM",
                "Saturday: 9:00 AM – 5:00 PM",
                "Sunday: 9:00 AM – 5:00 PM",
            ]
        },
        "website": "https://cityurgentcare.example.com",
    }
}

MOCK_EMPTY_RESPONSE = {"results": [], "status": "ZERO_RESULTS"}

USER_LOCATION = {"lat": USER_LAT, "lng": USER_LNG}


def _make_gmaps_mock(
    places_response: dict = None,
    details_response: dict = None,
) -> MagicMock:
    """Build a mock googlemaps Client whose relevant methods return given dicts."""
    gmaps = MagicMock()
    gmaps.places_nearby.return_value = places_response or MOCK_PLACES_RESPONSE
    gmaps.place.return_value = details_response or MOCK_PLACE_DETAILS_RESPONSE
    return gmaps


def _mock_gmaps(places_response=None, details_response=None):
    """Patch _get_gmaps_client to return a configured mock."""
    gmaps = _make_gmaps_mock(places_response, details_response)
    return patch("tools.find_care._get_gmaps_client", return_value=gmaps), gmaps


# ─────────────────────────────────────────────────────────────────────────────
# _haversine_miles
# ─────────────────────────────────────────────────────────────────────────────

def test_haversine_same_point_is_zero():
    dist = fc._haversine_miles(42.36, -71.06, 42.36, -71.06)
    assert dist == 0.0
    print("✓ test_haversine_same_point_is_zero")


def test_haversine_known_distance():
    # Boston → Cambridge (~3 miles) rough check
    dist = fc._haversine_miles(42.3601, -71.0589, 42.3736, -71.1097)
    assert 2.5 < dist < 4.5, f"Expected ~3 miles, got {dist}"
    print(f"✓ test_haversine_known_distance  ({dist} miles)")


def test_haversine_symmetrical():
    d1 = fc._haversine_miles(42.36, -71.06, 40.71, -74.01)
    d2 = fc._haversine_miles(40.71, -74.01, 42.36, -71.06)
    assert abs(d1 - d2) < 0.01
    print("✓ test_haversine_symmetrical")


def test_haversine_returns_float():
    result = fc._haversine_miles(42.0, -71.0, 42.1, -71.1)
    assert isinstance(result, float)
    print("✓ test_haversine_returns_float")


# ─────────────────────────────────────────────────────────────────────────────
# _hours_today
# ─────────────────────────────────────────────────────────────────────────────

WEEKDAY_TEXT = [
    "Monday: 8:00 AM – 8:00 PM",
    "Tuesday: 8:00 AM – 8:00 PM",
    "Wednesday: 8:00 AM – 8:00 PM",
    "Thursday: 8:00 AM – 8:00 PM",
    "Friday: 8:00 AM – 8:00 PM",
    "Saturday: 9:00 AM – 5:00 PM",
    "Sunday: Closed",
]


def test_hours_today_returns_string_from_list():
    # Pin to Monday (weekday=0)
    with patch("tools.find_care.datetime") as mock_dt:
        mock_dt.now.return_value.weekday.return_value = 0
        result = fc._hours_today(WEEKDAY_TEXT)
    assert result == "Monday: 8:00 AM – 8:00 PM"
    print("✓ test_hours_today_returns_string_from_list")


def test_hours_today_sunday():
    with patch("tools.find_care.datetime") as mock_dt:
        mock_dt.now.return_value.weekday.return_value = 6
        result = fc._hours_today(WEEKDAY_TEXT)
    assert result == "Sunday: Closed"
    print("✓ test_hours_today_sunday")


def test_hours_today_none_returns_fallback():
    result = fc._hours_today(None)
    assert "Google Maps" in result or "hours" in result.lower()
    print("✓ test_hours_today_none_returns_fallback")


def test_hours_today_empty_list_returns_fallback():
    result = fc._hours_today([])
    assert "Google Maps" in result or "hours" in result.lower()
    print("✓ test_hours_today_empty_list_returns_fallback")


def test_hours_today_out_of_range_idx_returns_fallback():
    # Provide only 5 entries but request idx=6 (Sunday)
    with patch("tools.find_care.datetime") as mock_dt:
        mock_dt.now.return_value.weekday.return_value = 6
        result = fc._hours_today(WEEKDAY_TEXT[:5])
    assert "Google Maps" in result or "hours" in result.lower()
    print("✓ test_hours_today_out_of_range_idx_returns_fallback")


# ─────────────────────────────────────────────────────────────────────────────
# _plan_value / _plan_confidence
# ─────────────────────────────────────────────────────────────────────────────

def test_plan_value_returns_value():
    assert fc._plan_value(MOCK_PLAN_JSON, "telehealth_copay") == "$0"
    print("✓ test_plan_value_returns_value")


def test_plan_value_none_plan_json():
    assert fc._plan_value(None, "telehealth_copay") is None
    print("✓ test_plan_value_none_plan_json")


def test_plan_value_missing_field():
    assert fc._plan_value(MOCK_PLAN_JSON, "nonexistent") is None
    print("✓ test_plan_value_missing_field")


def test_plan_confidence_returns_confidence():
    assert fc._plan_confidence(MOCK_PLAN_JSON, "telehealth_copay") == "HIGH"
    print("✓ test_plan_confidence_returns_confidence")


def test_plan_confidence_none_plan_json():
    assert fc._plan_confidence(None, "telehealth_copay") == "MISSING"
    print("✓ test_plan_confidence_none_plan_json")


# ─────────────────────────────────────────────────────────────────────────────
# _telehealth_result
# ─────────────────────────────────────────────────────────────────────────────

def test_telehealth_result_with_plan():
    r = fc._telehealth_result(MOCK_PLAN_JSON)
    assert r["name"] == "Telehealth via your insurance"
    assert r["copay"] == "$0"
    assert r["confidence"] == "HIGH"
    assert r["insurer_url"] == "https://example.com/find"
    assert "insurer's app" in r["note"]
    print("✓ test_telehealth_result_with_plan")


def test_telehealth_result_none_plan():
    r = fc._telehealth_result(None)
    assert r["name"] == "Telehealth via your insurance"
    assert r["copay"] is None
    assert r["insurer_url"] is None
    assert r["confidence"] == "MISSING"
    print("✓ test_telehealth_result_none_plan")


def test_telehealth_result_has_all_keys():
    r = fc._telehealth_result(MOCK_PLAN_JSON)
    for key in ("name", "note", "insurer_url", "copay", "confidence"):
        assert key in r, f"missing key '{key}'"
    print("✓ test_telehealth_result_has_all_keys")


# ─────────────────────────────────────────────────────────────────────────────
# _format_result
# ─────────────────────────────────────────────────────────────────────────────

MOCK_DETAILS = {
    "formatted_phone_number": "(617) 555-9999",
    "opening_hours": {"weekday_text": WEEKDAY_TEXT},
    "website": "https://example-clinic.com",
}


def test_format_result_all_fields_present():
    with patch("tools.find_care.datetime") as mock_dt:
        mock_dt.now.return_value.weekday.return_value = 0  # Monday
        result = fc._format_result(MOCK_PLACE_1, MOCK_DETAILS, USER_LAT, USER_LNG)

    required = (
        "name", "address", "distance_miles", "is_open_now", "hours_today",
        "phone", "google_maps_url", "booking_url", "rating", "rating_count",
        "network_status", "network_note",
    )
    for key in required:
        assert key in result, f"missing key '{key}'"
    print("✓ test_format_result_all_fields_present")


def test_format_result_network_status_always_verify_required():
    result = fc._format_result(MOCK_PLACE_1, MOCK_DETAILS, USER_LAT, USER_LNG)
    assert result["network_status"] == "verify_required"
    print("✓ test_format_result_network_status_always_verify_required")


def test_format_result_network_note_exact_string():
    result = fc._format_result(MOCK_PLACE_1, MOCK_DETAILS, USER_LAT, USER_LNG)
    assert result["network_note"] == "Call to verify if this provider accepts your insurance"
    print("✓ test_format_result_network_note_exact_string")


def test_format_result_google_maps_url_contains_place_id():
    result = fc._format_result(MOCK_PLACE_1, MOCK_DETAILS, USER_LAT, USER_LNG)
    assert "ChIJplace1" in result["google_maps_url"]
    assert "google.com/maps" in result["google_maps_url"]
    print("✓ test_format_result_google_maps_url_contains_place_id")


def test_format_result_phone_from_details():
    result = fc._format_result(MOCK_PLACE_1, MOCK_DETAILS, USER_LAT, USER_LNG)
    assert result["phone"] == "(617) 555-9999"
    print("✓ test_format_result_phone_from_details")


def test_format_result_no_phone_when_details_empty():
    result = fc._format_result(MOCK_PLACE_1, {}, USER_LAT, USER_LNG)
    assert result["phone"] is None
    print("✓ test_format_result_no_phone_when_details_empty")


def test_format_result_booking_url_from_website():
    result = fc._format_result(MOCK_PLACE_1, MOCK_DETAILS, USER_LAT, USER_LNG)
    assert result["booking_url"] == "https://example-clinic.com"
    print("✓ test_format_result_booking_url_from_website")


def test_format_result_no_booking_url_when_no_website():
    result = fc._format_result(MOCK_PLACE_1, {}, USER_LAT, USER_LNG)
    assert result["booking_url"] is None
    print("✓ test_format_result_no_booking_url_when_no_website")


def test_format_result_distance_nonnegative():
    result = fc._format_result(MOCK_PLACE_1, {}, USER_LAT, USER_LNG)
    assert result["distance_miles"] >= 0
    print("✓ test_format_result_distance_nonnegative")


def test_format_result_rating_is_float_or_none():
    result = fc._format_result(MOCK_PLACE_1, {}, USER_LAT, USER_LNG)
    assert isinstance(result["rating"], float)
    result_no_rating = fc._format_result({**MOCK_PLACE_1, "rating": None}, {}, USER_LAT, USER_LNG)
    assert result_no_rating["rating"] is None
    print("✓ test_format_result_rating_is_float_or_none")


def test_format_result_rating_count_is_int_or_none():
    result = fc._format_result(MOCK_PLACE_1, {}, USER_LAT, USER_LNG)
    assert isinstance(result["rating_count"], int)
    result_no_count = fc._format_result({**MOCK_PLACE_1, "user_ratings_total": None}, {}, USER_LAT, USER_LNG)
    assert result_no_count["rating_count"] is None
    print("✓ test_format_result_rating_count_is_int_or_none")


def test_format_result_is_open_now_bool():
    result_open = fc._format_result(MOCK_PLACE_1, {}, USER_LAT, USER_LNG)  # open_now=True
    assert result_open["is_open_now"] is True
    result_closed = fc._format_result(MOCK_PLACE_2, {}, USER_LAT, USER_LNG)  # open_now=False
    assert result_closed["is_open_now"] is False
    print("✓ test_format_result_is_open_now_bool")


# ─────────────────────────────────────────────────────────────────────────────
# run_find_care — integration tests (Google Maps mocked)
# ─────────────────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def test_telehealth_care_type_skips_maps():
    """care_type='telehealth' must never call Google Maps."""
    mock_ctx, gmaps_mock = _mock_gmaps()
    with mock_ctx:
        result = _run(fc.run_find_care(
            care_type="telehealth",
            location=USER_LOCATION,
            plan_json=MOCK_PLAN_JSON,
            user_language="en",
        ))
    gmaps_mock.places_nearby.assert_not_called()
    assert result["care_type"] == "telehealth"
    assert result["telehealth_fallback"] is False
    r = result["results"][0]
    assert r["name"] == "Telehealth via your insurance"
    assert r["copay"] == "$0"
    assert r["insurer_url"] == "https://example.com/find"
    print("✓ test_telehealth_care_type_skips_maps")


def test_telehealth_result_structure():
    """Telehealth response has required top-level keys."""
    mock_ctx, _ = _mock_gmaps()
    with mock_ctx:
        result = _run(fc.run_find_care("telehealth", USER_LOCATION, plan_json=None))
    for key in ("care_type", "results", "telehealth_fallback", "user_language"):
        assert key in result, f"missing top-level key '{key}'"
    print("✓ test_telehealth_result_structure")


def test_no_results_returns_telehealth_fallback():
    """Empty Places response → telehealth_fallback=True."""
    mock_ctx, _ = _mock_gmaps(places_response=MOCK_EMPTY_RESPONSE)
    with mock_ctx:
        result = _run(fc.run_find_care(
            care_type="urgent_care",
            location=USER_LOCATION,
            plan_json=MOCK_PLAN_JSON,
        ))
    assert result["telehealth_fallback"] is True
    assert result["results"][0]["name"] == "Telehealth via your insurance"
    print("✓ test_no_results_returns_telehealth_fallback")


def test_api_failure_returns_telehealth_fallback():
    """Google Maps API exception → telehealth_fallback=True."""
    with patch("tools.find_care._get_gmaps_client") as mock_factory:
        mock_factory.side_effect = Exception("API key invalid")
        result = _run(fc.run_find_care(
            care_type="urgent_care",
            location=USER_LOCATION,
            plan_json=MOCK_PLAN_JSON,
        ))
    assert result["telehealth_fallback"] is True
    print("✓ test_api_failure_returns_telehealth_fallback")


def test_places_nearby_exception_returns_telehealth_fallback():
    """places_nearby() raising → telehealth_fallback=True."""
    with patch("tools.find_care._get_gmaps_client") as mock_factory:
        gmaps = MagicMock()
        gmaps.places_nearby.side_effect = Exception("quota exceeded")
        mock_factory.return_value = gmaps
        result = _run(fc.run_find_care("urgent_care", USER_LOCATION, plan_json=None))
    assert result["telehealth_fallback"] is True
    print("✓ test_places_nearby_exception_returns_telehealth_fallback")


def test_results_capped_at_five():
    """Even if Maps returns more than 5 places, output is capped at MAX_RESULTS."""
    many_places = []
    for i in range(8):
        many_places.append({
            "place_id": f"ChIJ{i}",
            "name": f"Clinic {i}",
            "vicinity": f"{i} Main St",
            "geometry": {"location": {"lat": USER_LAT + i * 0.01, "lng": USER_LNG}},
            "opening_hours": {"open_now": True},
            "rating": 4.0,
            "user_ratings_total": 50,
        })
    mock_ctx, _ = _mock_gmaps(places_response={"results": many_places})
    with mock_ctx:
        result = _run(fc.run_find_care("urgent_care", USER_LOCATION))
    assert len(result["results"]) <= fc.MAX_RESULTS
    print(f"✓ test_results_capped_at_five  ({len(result['results'])} results)")


def test_results_sorted_by_distance():
    """Results must be in ascending distance order."""
    # MOCK_PLACE_2 is farther than MOCK_PLACE_1 — we put MOCK_PLACE_2 first in
    # the API response to verify our own sorting step actually runs.
    swapped_response = {"results": [MOCK_PLACE_2, MOCK_PLACE_1]}
    mock_ctx, _ = _mock_gmaps(places_response=swapped_response)
    with mock_ctx:
        result = _run(fc.run_find_care("urgent_care", USER_LOCATION))
    distances = [r["distance_miles"] for r in result["results"]]
    assert distances == sorted(distances), f"Not sorted: {distances}"
    # Nearest should be MOCK_PLACE_1 (near user location)
    assert result["results"][0]["name"] == "City Urgent Care"
    print(f"✓ test_results_sorted_by_distance  distances={distances}")


def test_output_structure_all_fields():
    """Full pipeline result has all required keys including per-result fields."""
    mock_ctx, _ = _mock_gmaps()
    with mock_ctx:
        result = _run(fc.run_find_care("urgent_care", USER_LOCATION, plan_json=MOCK_PLAN_JSON))

    for key in ("care_type", "results", "telehealth_fallback", "user_language"):
        assert key in result, f"top-level key missing: '{key}'"

    assert result["care_type"] == "urgent_care"
    assert result["telehealth_fallback"] is False
    assert len(result["results"]) > 0

    r = result["results"][0]
    for key in ("name", "address", "distance_miles", "is_open_now", "hours_today",
                "phone", "google_maps_url", "booking_url", "rating", "rating_count",
                "network_status", "network_note"):
        assert key in r, f"result key missing: '{key}'"
    print("✓ test_output_structure_all_fields")


def test_network_status_always_verify_required():
    """Every provider card must have network_status = 'verify_required'."""
    mock_ctx, _ = _mock_gmaps()
    with mock_ctx:
        result = _run(fc.run_find_care("urgent_care", USER_LOCATION))
    for r in result["results"]:
        assert r["network_status"] == "verify_required"
    print("✓ test_network_status_always_verify_required")


def test_network_note_exact_string():
    """network_note must be exactly the required string from CLAUDE.md."""
    mock_ctx, _ = _mock_gmaps()
    with mock_ctx:
        result = _run(fc.run_find_care("pcp", USER_LOCATION))
    for r in result["results"]:
        assert r["network_note"] == "Call to verify if this provider accepts your insurance"
    print("✓ test_network_note_exact_string")


def test_plan_none_graceful_for_regular_care():
    """plan_json=None should not crash; results still returned."""
    mock_ctx, _ = _mock_gmaps()
    with mock_ctx:
        result = _run(fc.run_find_care("urgent_care", USER_LOCATION, plan_json=None))
    assert result is not None
    assert len(result["results"]) > 0
    print("✓ test_plan_none_graceful_for_regular_care")


def test_plan_none_telehealth_fallback_has_null_insurer_url():
    """Telehealth fallback with plan_json=None → insurer_url is None."""
    mock_ctx, _ = _mock_gmaps(places_response=MOCK_EMPTY_RESPONSE)
    with mock_ctx:
        result = _run(fc.run_find_care("urgent_care", USER_LOCATION, plan_json=None))
    assert result["telehealth_fallback"] is True
    assert result["results"][0]["insurer_url"] is None
    print("✓ test_plan_none_telehealth_fallback_has_null_insurer_url")


def test_user_language_echoed():
    mock_ctx, _ = _mock_gmaps()
    with mock_ctx:
        result = _run(fc.run_find_care("pharmacy", USER_LOCATION, user_language="zh"))
    assert result["user_language"] == "zh"
    print("✓ test_user_language_echoed")


def test_all_care_type_mapping_keys_accepted():
    """Every key in CARE_TYPE_MAPPING must produce a valid response."""
    for ct in fc.CARE_TYPE_MAPPING:
        mock_ctx, _ = _mock_gmaps()
        with mock_ctx:
            result = _run(fc.run_find_care(ct, USER_LOCATION, plan_json=MOCK_PLAN_JSON))
        assert "results" in result, f"{ct}: missing 'results'"
        assert "care_type" in result, f"{ct}: missing 'care_type'"
    print("✓ test_all_care_type_mapping_keys_accepted")


def test_unknown_care_type_returns_telehealth_fallback():
    """Unknown care_type not in mapping → telehealth fallback."""
    mock_ctx, _ = _mock_gmaps()
    with mock_ctx:
        result = _run(fc.run_find_care("helicopter", USER_LOCATION, plan_json=MOCK_PLAN_JSON))
    assert result["telehealth_fallback"] is True
    print("✓ test_unknown_care_type_returns_telehealth_fallback")


def test_open_now_passed_to_places_api():
    """open_now parameter must be forwarded to gmaps.places_nearby."""
    mock_ctx, gmaps_mock = _mock_gmaps()
    with mock_ctx:
        _run(fc.run_find_care("urgent_care", USER_LOCATION, open_now=False))
    call_kwargs = gmaps_mock.places_nearby.call_args
    assert call_kwargs.kwargs.get("open_now") is False or call_kwargs[1].get("open_now") is False
    print("✓ test_open_now_passed_to_places_api")


def test_place_details_called_per_result():
    """gmaps.place must be called once per result in the top-N list."""
    mock_ctx, gmaps_mock = _mock_gmaps()
    with mock_ctx:
        result = _run(fc.run_find_care("urgent_care", USER_LOCATION))
    assert gmaps_mock.place.call_count == len(result["results"])
    print(f"✓ test_place_details_called_per_result  ({gmaps_mock.place.call_count} calls)")


def test_er_care_type_uses_correct_keyword():
    """'er' care_type must query 'emergency room hospital'."""
    mock_ctx, gmaps_mock = _mock_gmaps()
    with mock_ctx:
        _run(fc.run_find_care("er", USER_LOCATION))
    call_kwargs = gmaps_mock.places_nearby.call_args
    keyword = call_kwargs.kwargs.get("keyword") or call_kwargs[1].get("keyword")
    assert keyword == "emergency room hospital"
    print("✓ test_er_care_type_uses_correct_keyword")


def test_pt_care_type_uses_correct_keyword():
    mock_ctx, gmaps_mock = _mock_gmaps()
    with mock_ctx:
        _run(fc.run_find_care("pt", USER_LOCATION))
    call_kwargs = gmaps_mock.places_nearby.call_args
    keyword = call_kwargs.kwargs.get("keyword") or call_kwargs[1].get("keyword")
    assert keyword == "physical therapy clinic"
    print("✓ test_pt_care_type_uses_correct_keyword")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    test_haversine_same_point_is_zero,
    test_haversine_known_distance,
    test_haversine_symmetrical,
    test_haversine_returns_float,
    test_hours_today_returns_string_from_list,
    test_hours_today_sunday,
    test_hours_today_none_returns_fallback,
    test_hours_today_empty_list_returns_fallback,
    test_hours_today_out_of_range_idx_returns_fallback,
    test_plan_value_returns_value,
    test_plan_value_none_plan_json,
    test_plan_value_missing_field,
    test_plan_confidence_returns_confidence,
    test_plan_confidence_none_plan_json,
    test_telehealth_result_with_plan,
    test_telehealth_result_none_plan,
    test_telehealth_result_has_all_keys,
    test_format_result_all_fields_present,
    test_format_result_network_status_always_verify_required,
    test_format_result_network_note_exact_string,
    test_format_result_google_maps_url_contains_place_id,
    test_format_result_phone_from_details,
    test_format_result_no_phone_when_details_empty,
    test_format_result_booking_url_from_website,
    test_format_result_no_booking_url_when_no_website,
    test_format_result_distance_nonnegative,
    test_format_result_rating_is_float_or_none,
    test_format_result_rating_count_is_int_or_none,
    test_format_result_is_open_now_bool,
    test_telehealth_care_type_skips_maps,
    test_telehealth_result_structure,
    test_no_results_returns_telehealth_fallback,
    test_api_failure_returns_telehealth_fallback,
    test_places_nearby_exception_returns_telehealth_fallback,
    test_results_capped_at_five,
    test_results_sorted_by_distance,
    test_output_structure_all_fields,
    test_network_status_always_verify_required,
    test_network_note_exact_string,
    test_plan_none_graceful_for_regular_care,
    test_plan_none_telehealth_fallback_has_null_insurer_url,
    test_user_language_echoed,
    test_all_care_type_mapping_keys_accepted,
    test_unknown_care_type_returns_telehealth_fallback,
    test_open_now_passed_to_places_api,
    test_place_details_called_per_result,
    test_er_care_type_uses_correct_keyword,
    test_pt_care_type_uses_correct_keyword,
]

if __name__ == "__main__":
    print("=" * 60)
    print("Birdie find_care test suite")
    print("=" * 60)
    passed = 0
    failed = 0
    for fn in ALL_TESTS:
        try:
            fn()
            passed += 1
        except Exception as exc:
            print(f"✗ {fn.__name__}")
            print(f"  ERROR: {exc}")
            import traceback
            traceback.print_exc()
            failed += 1
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
