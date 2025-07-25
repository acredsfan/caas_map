"""
Custom exception classes for State Tier Map application
"""

class ValidationError(Exception):
    """Raised when input validation fails"""
    pass

class GeocodingError(Exception):
    """Raised when geocoding fails unexpectedly"""
    pass

class MapGenerationError(Exception):
    """Raised during map creation or rendering errors"""
    pass
