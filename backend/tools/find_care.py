"""find_care: finds nearby healthcare providers via Google Maps Places API.
See CLAUDE.md for full spec.

Architecture:
  1. Telehealth special case — skip Maps entirely, return insurer plan data
  2. Google Maps Places Nearby search via care_type → keyword mapping
  3. Haversine distance calculation, sort ascending, cap at 5 results
  4. Place Details call per result for phone, hours_today, and booking_url
  5. Fallback to telehealth when no results or API failure

Hard rules enforced (CLAUDE.md):
  - network_status ALWAYS "verify_required" — never confirm in-network status
  - network_note ALWAYS the exact required string
  - Google Maps no results → telehealth fallback with insurer_provider_finder_url
  - plan_json None handled gracefully throughout
"""

import math
import os
from datetime import datetime
from typing import Optional

import googlemaps

from config import (
    CARE_TYPE_MAPPING,
    MAX_RESULTS,
    NETWORK_NOTE,
    NETWORK_STATUS,
    SEARCH_RADIUS_METERS,
    SPECIALIST_SEARCH_RADIUS,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_gmaps_client() -> googlemaps.Client:
    """Build a Google Maps client from the environment API key."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    return googlemaps.Client(key=api_key)


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate great-circle distance in miles between two lat/lng points."""
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return round(2 * R * math.asin(math.sqrt(a)), 2)


def _hours_today(weekday_text: Optional[list]) -> str:
    """Extract today's hours string from a weekday_text list.

    Google's weekday_text is ordered Monday=0 … Sunday=6, matching
    Python's datetime.weekday() convention.
    """
    if not weekday_text or not isinstance(weekday_text, list):
        return "See Google Maps for hours"
    today_idx = datetime.now().weekday()
    if today_idx < len(weekday_text):
        return weekday_text[today_idx]
    return "See Google Maps for hours"


def _plan_value(plan_json: Optional[dict], field: str):
    """Safely return the .value of a plan field."""
    if not plan_json:
        return None
    entry = plan_json.get(field)
    return entry.get("value") if isinstance(entry, dict) else None


def _plan_confidence(plan_json: Optional[dict], field: str) -> str:
    """Safely return the .confidence of a plan field."""
    if not plan_json:
        return "MISSING"
    entry = plan_json.get(field)
    return entry.get("confidence", "MISSING") if isinstance(entry, dict) else "MISSING"


# ── Telehealth special case ────────────────────────────────────────────────────

def _telehealth_result(plan_json: Optional[dict]) -> dict:
    """Build the telehealth special-case result entry per CLAUDE.md spec."""
    return {
        "name": "Telehealth via your insurance",
        "note": "Log into your insurer's app or website to start a telehealth visit",
        "insurer_url": _plan_value(plan_json, "insurer_provider_finder_url"),
        "copay": _plan_value(plan_json, "telehealth_copay"),
        "confidence": _plan_confidence(plan_json, "telehealth_copay"),
    }


def _telehealth_response(
    care_type: str,
    plan_json: Optional[dict],
    user_language: str,
    telehealth_fallback: bool,
) -> dict:
    return {
        "care_type": care_type,
        "results": [_telehealth_result(plan_json)],
        "telehealth_fallback": telehealth_fallback,
        "user_language": user_language,
    }


# ── Place details ──────────────────────────────────────────────────────────────

def _get_place_details(gmaps_client: googlemaps.Client, place_id: str, language: str) -> dict:
    """Fetch phone, opening hours, and website for a place.

    Returns empty dict on any failure so callers always get a safe value.
    """
    try:
        details = gmaps_client.place(  # type: ignore[attr-defined]
            place_id=place_id,
            fields=["formatted_phone_number", "opening_hours", "website"],
            language=language,
        )
        return details.get("result", {})
    except Exception:
        return {}


# ── Result formatting ──────────────────────────────────────────────────────────

def _format_result(
    place: dict,
    details: dict,
    user_lat: float,
    user_lng: float,
) -> dict:
    """Build a single provider card from Places Nearby + Place Details data."""
    geo = place.get("geometry", {}).get("location", {})
    place_lat = geo.get("lat", user_lat)
    place_lng = geo.get("lng", user_lng)

    place_id = place.get("place_id", "")
    google_maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

    opening_hours_nearby = place.get("opening_hours", {})
    is_open_now = bool(opening_hours_nearby.get("open_now", False))

    detail_opening = details.get("opening_hours", {})
    hours = _hours_today(detail_opening.get("weekday_text"))

    phone: Optional[str] = details.get("formatted_phone_number") or None
    booking_url: Optional[str] = details.get("website") or None

    raw_rating = place.get("rating")
    raw_count = place.get("user_ratings_total")

    return {
        "name": place.get("name", "Unknown"),
        "address": place.get("vicinity", ""),
        "distance_miles": _haversine_miles(user_lat, user_lng, place_lat, place_lng),
        "is_open_now": is_open_now,
        "hours_today": hours,
        "phone": phone,
        "google_maps_url": google_maps_url,
        "booking_url": booking_url,
        "rating": float(raw_rating) if raw_rating is not None else None,
        "rating_count": int(raw_count) if raw_count is not None else None,
        "network_status": NETWORK_STATUS,
        "network_note": NETWORK_NOTE,
    }


# ── Public API ─────────────────────────────────────────────────────────────────

async def run_find_care(
    care_type: str,
    location: dict,
    open_now: bool = True,
    plan_json: Optional[dict] = None,
    user_language: str = "en",
    search_query: Optional[str] = None,
) -> dict:
    """Find nearby providers for a given care_type.

    Returns:
      - Telehealth special-case response when care_type == "telehealth"
      - Up to 5 provider cards sorted by distance for physical care types
      - Telehealth fallback on no results or API failure (CLAUDE.md fallback rule)

    plan_json=None is handled gracefully; telehealth results show null copay/URL.
    """
    lat = float(location.get("lat", 0))
    lng = float(location.get("lng", 0))
    lang_code = (user_language or "en")[:2]

    # Telehealth special case — skip Maps entirely (CLAUDE.md)
    if care_type == "telehealth":
        return _telehealth_response("telehealth", plan_json, user_language, telehealth_fallback=False)

    # For "specialist" care_type, use the search_query from intent classifier
    if care_type == "specialist" and search_query:
        keyword = search_query
    else:
        keyword = CARE_TYPE_MAPPING.get(care_type)
    if keyword is None:
        # Unknown care_type falls back to telehealth
        return _telehealth_response(care_type, plan_json, user_language, telehealth_fallback=True)

    # Specialists are sparser — use wider search radius
    radius = SPECIALIST_SEARCH_RADIUS if care_type == "specialist" else SEARCH_RADIUS_METERS

    try:
        gmaps = _get_gmaps_client()
        response = gmaps.places_nearby(  # type: ignore[attr-defined]
            location=(lat, lng),
            radius=radius,
            keyword=keyword,
            open_now=open_now,
            language=lang_code,
        )
        places = response.get("results", [])

        # If open_now returned no results, retry without the filter.
        # Appointment-based care (PT, PCP, mental health) may be closed
        # at the time of search but still useful to show.
        if not places and open_now:
            response = gmaps.places_nearby(  # type: ignore[attr-defined]
                location=(lat, lng),
                radius=radius,
                keyword=keyword,
                language=lang_code,
            )
            places = response.get("results", [])

    except Exception:
        # API failure → telehealth fallback (CLAUDE.md fallback rule)
        return _telehealth_response(care_type, plan_json, user_language, telehealth_fallback=True)

    if not places:
        # No results even without open_now → telehealth fallback
        return _telehealth_response(care_type, plan_json, user_language, telehealth_fallback=True)

    # Calculate distance for each place, sort ascending, take top MAX_RESULTS
    scored: list[tuple[float, dict]] = []
    for place in places:
        geo = place.get("geometry", {}).get("location", {})
        dist = _haversine_miles(lat, lng, geo.get("lat", lat), geo.get("lng", lng))
        scored.append((dist, place))
    scored.sort(key=lambda x: x[0])
    top_places = [p for _, p in scored[:MAX_RESULTS]]

    # Fetch details per place, format results
    results = []
    for place in top_places:
        place_id = place.get("place_id", "")
        details = _get_place_details(gmaps, place_id, lang_code) if place_id else {}
        results.append(_format_result(place, details, lat, lng))

    return {
        "care_type": care_type,
        "results": results,
        "telehealth_fallback": False,
        "user_language": user_language,
    }
