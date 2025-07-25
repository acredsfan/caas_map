"""
Enhanced validation utilities for location pins data with coordinate support.

This module provides validation functions that support both the original address-based
format and the new enhanced format with latitude/longitude coordinates.
"""

import pandas as pd
from typing import Set, List, Tuple, Optional


def validate_enhanced_location_pins(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """
    Validate location pins DataFrame with enhanced coordinate support.
    
    Args:
        df: DataFrame to validate
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    # Required columns that must always be present
    required_cols = {"Location Name", "Electrification Candidates", "Category Name"}
    missing_required = required_cols - set(df.columns)
    if missing_required:
        errors.append(f"Missing required columns: {', '.join(missing_required)}")
        return False, errors
    
    # Check that we have location data (either address-based or coordinate-based)
    location_validation_result = validate_location_data(df)
    if not location_validation_result[0]:
        errors.extend(location_validation_result[1])
    
    # Validate Electrification Candidates column
    candidates_validation = validate_electrification_candidates(df)
    if not candidates_validation[0]:
        errors.extend(candidates_validation[1])
    
    # Validate coordinates if present
    coord_validation = validate_coordinates(df)
    if not coord_validation[0]:
        errors.extend(coord_validation[1])
    
    return len(errors) == 0, errors


def validate_location_data(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """
    Validate that each row has sufficient location data for geocoding.
    
    Args:
        df: DataFrame to validate
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    # Check each row for valid location data
    invalid_rows = []
    
    for idx, row in df.iterrows():
        has_coordinates = (
            'Latitude' in df.columns and 'Longitude' in df.columns and
            pd.notna(row.get('Latitude')) and pd.notna(row.get('Longitude')) and
            str(row.get('Latitude')).strip() != '' and str(row.get('Longitude')).strip() != ''
        )
        
        has_zip = (
            'ZIP/Postal Code' in df.columns and
            pd.notna(row.get('ZIP/Postal Code')) and
            str(row.get('ZIP/Postal Code')).strip() != ''
        )
        
        has_city_state = (
            'City' in df.columns and 'State' in df.columns and
            pd.notna(row.get('City')) and pd.notna(row.get('State')) and
            str(row.get('City')).strip() != '' and str(row.get('State')).strip() != ''
        )
        
        has_street_address = (
            'Street Address' in df.columns and
            pd.notna(row.get('Street Address')) and
            str(row.get('Street Address')).strip() != ''
        )
        
        # A row is valid if it has coordinates OR sufficient address information
        if not (has_coordinates or has_zip or has_city_state or has_street_address):
            invalid_rows.append(idx + 2)  # +2 for 1-based indexing and header row
    
    if invalid_rows:
        if len(invalid_rows) <= 5:
            rows_str = ", ".join(map(str, invalid_rows))
        else:
            rows_str = f"{', '.join(map(str, invalid_rows[:5]))} and {len(invalid_rows) - 5} more"
        
        errors.append(
            f"Rows {rows_str} lack sufficient location data. Each row must have either: "
            f"1) Latitude and Longitude coordinates, OR "
            f"2) ZIP/Postal Code, OR "
            f"3) City and State, OR "
            f"4) Street Address"
        )
    
    return len(errors) == 0, errors


def validate_electrification_candidates(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """
    Validate the Electrification Candidates column.
    
    Args:
        df: DataFrame to validate
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    if 'Electrification Candidates' not in df.columns:
        errors.append("Missing required column: Electrification Candidates")
        return False, errors
    
    # Check for non-numeric values
    invalid_candidates = []
    for idx, value in df['Electrification Candidates'].items():
        try:
            num_val = float(str(value).strip())
            if not num_val.is_integer() or num_val <= 0:
                invalid_candidates.append(idx + 2)
        except (ValueError, AttributeError):
            invalid_candidates.append(idx + 2)
    
    if invalid_candidates:
        if len(invalid_candidates) <= 5:
            rows_str = ", ".join(map(str, invalid_candidates))
        else:
            rows_str = f"{', '.join(map(str, invalid_candidates[:5]))} and {len(invalid_candidates) - 5} more"
        
        errors.append(
            f"Rows {rows_str} have invalid Electrification Candidates values. "
            f"Must be positive integers (1, 2, 3, etc.)"
        )
    
    return len(errors) == 0, errors


def validate_coordinates(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """
    Validate latitude and longitude coordinates if present.
    
    Args:
        df: DataFrame to validate
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    if 'Latitude' not in df.columns and 'Longitude' not in df.columns:
        return True, errors  # No coordinates to validate
    
    if 'Latitude' in df.columns:
        invalid_lat_rows = []
        for idx, value in df['Latitude'].items():
            if pd.notna(value) and str(value).strip() != '':
                try:
                    lat_val = float(str(value).strip())
                    if not (-90 <= lat_val <= 90):
                        invalid_lat_rows.append(idx + 2)
                except (ValueError, AttributeError):
                    invalid_lat_rows.append(idx + 2)
        
        if invalid_lat_rows:
            if len(invalid_lat_rows) <= 5:
                rows_str = ", ".join(map(str, invalid_lat_rows))
            else:
                rows_str = f"{', '.join(map(str, invalid_lat_rows[:5]))} and {len(invalid_lat_rows) - 5} more"
            
            errors.append(
                f"Rows {rows_str} have invalid Latitude values. "
                f"Must be numbers between -90 and 90 degrees"
            )
    
    if 'Longitude' in df.columns:
        invalid_lon_rows = []
        for idx, value in df['Longitude'].items():
            if pd.notna(value) and str(value).strip() != '':
                try:
                    lon_val = float(str(value).strip())
                    if not (-180 <= lon_val <= 180):
                        invalid_lon_rows.append(idx + 2)
                except (ValueError, AttributeError):
                    invalid_lon_rows.append(idx + 2)
        
        if invalid_lon_rows:
            if len(invalid_lon_rows) <= 5:
                rows_str = ", ".join(map(str, invalid_lon_rows))
            else:
                rows_str = f"{', '.join(map(str, invalid_lon_rows[:5]))} and {len(invalid_lon_rows) - 5} more"
            
            errors.append(
                f"Rows {rows_str} have invalid Longitude values. "
                f"Must be numbers between -180 and 180 degrees"
            )
    
    return len(errors) == 0, errors


def get_enhanced_required_columns() -> Set[str]:
    """
    Get the set of required columns for enhanced location pins format.
    
    Returns:
        Set of required column names
    """
    return {"Location Name", "Electrification Candidates", "Category Name"}


def get_enhanced_optional_columns() -> Set[str]:
    """
    Get the set of optional columns for enhanced location pins format.
    
    Returns:
        Set of optional column names
    """
    return {
        "Street Address", "City", "State", "ZIP/Postal Code", 
        "Latitude", "Longitude"
    }


def get_all_supported_columns() -> Set[str]:
    """
    Get all supported columns for enhanced location pins format.
    
    Returns:
        Set of all supported column names
    """
    return get_enhanced_required_columns() | get_enhanced_optional_columns()


# Backwards compatibility function
def validate_columns(df: pd.DataFrame, required_cols: Set[str]) -> bool:
    """
    Legacy validation function for backwards compatibility.
    
    Args:
        df: DataFrame to validate
        required_cols: Set of required column names
        
    Returns:
        True if all required columns are present
    """
    missing = required_cols - set(df.columns)
    return len(missing) == 0
