"""
Utility functions for geocoding addresses
"""
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import requests
from shapely.geometry import Point

# Folium version geocoder
def geocode_nominatim(address: str, retries: int =3, delay: float=1.0):
    geolocator = Nominatim(user_agent="state_tier_map")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=delay, max_retries=retries)
    loc = geocode(address)
    if loc:
        return loc.latitude, loc.longitude
    return None, None

# Google Maps geocode
def google_geocode(address: str, api_key: str, timeout: int =5):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address, "key": api_key}
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception:
        pass
    return None, None

# Build fallback sequence for address string (legacy version)
def build_address_string_legacy(row: pd.Series) -> str:
    city = str(row.get("City", "")).strip()
    state = str(row.get("State", "")).strip()
    zipc = str(row.get("ZIP/Postal Code", "")).strip()
    if city and state and zipc:
        return f"{city}, {state} {zipc}, USA"
    if city and state:
        return f"{city}, {state}, USA"
    if zipc:
        return f"{zipc}, USA"
    return "USA"

# Snap to state centroid fallback
def snap_to_state_centroid(state_abbr: str, state_gdf):
    if state_abbr in state_gdf["StateAbbr"].values:
        geom = state_gdf[state_gdf["StateAbbr"] == state_abbr].geometry.values[0]
        centroid = geom.centroid
        return centroid.y, centroid.x
    return None, None

# Enhanced geocoding that checks for existing lat/lon coordinates first
def get_coordinates(row: pd.Series, geocode_func, state_gdf=None):
    """
    Get coordinates for a location, checking existing lat/lon first, then geocoding address.
    
    Args:
        row: DataFrame row with location data
        geocode_func: Function to use for geocoding (geocode_nominatim or google_geocode)
        state_gdf: State geodataframe for fallback centroid lookup
        
    Returns:
        Tuple of (latitude, longitude) or (None, None) if geocoding fails
    """
    # First check if we already have coordinates
    lat = row.get("Latitude", "")
    lon = row.get("Longitude", "")
    
    if lat and lon:
        try:
            lat_float = float(str(lat).strip())
            lon_float = float(str(lon).strip())
            # Validate coordinates are reasonable
            if -90 <= lat_float <= 90 and -180 <= lon_float <= 180:
                return lat_float, lon_float
        except (ValueError, TypeError):
            pass
    
    # If no valid coordinates, try geocoding the address
    address = build_address_string(row)
    if geocode_func == geocode_nominatim:
        return geocode_func(address)
    else:
        # Assume google_geocode which needs API key
        return None, None  # Would need API key parameter
    
    # Fallback to state centroid if available
    if state_gdf is not None:
        state_abbr = str(row.get("State", "")).strip().upper()
        if state_abbr:
            return snap_to_state_centroid(state_abbr, state_gdf)
    
    return None, None

# Enhanced address builder that also checks Street Address column
def build_address_string(row: pd.Series) -> str:
    """Build address string from available address components."""
    street = str(row.get("Street Address", "")).strip()
    city = str(row.get("City", "")).strip()
    state = str(row.get("State", "")).strip()
    zipc = str(row.get("ZIP/Postal Code", "")).strip()
    
    # Start with street address if available
    address_parts = []
    if street:
        address_parts.append(street)
    
    if city and state and zipc:
        address_parts.append(f"{city}, {state} {zipc}")
    elif city and state:
        address_parts.append(f"{city}, {state}")
    elif zipc:
        address_parts.append(zipc)
    
    if address_parts:
        return ", ".join(address_parts) + ", USA"
    
    return "USA"
