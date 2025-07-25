"""
Utility functions for input validation
"""
from flask import abort

def validate_columns(df, required_cols):
    """
    Ensure DataFrame contains required columns, aborts with 400 if missing.
    """
    missing = set(required_cols) - set(df.columns)
    if missing:
        abort(400, description=f"Missing required columns: {', '.join(missing)}")


def validate_str_length(value: str, max_length: int):
    """
    Validate string input length, aborts with 400 if exceeds.
    """
    if value and len(value) > max_length:
        abort(400, description=f"Input too long (max {max_length} characters)")
    return value[:max_length]
