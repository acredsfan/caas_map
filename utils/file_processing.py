"""
Utility functions for file upload and processing
"""
import os
import uuid
import pandas as pd
from werkzeug.utils import secure_filename

# Allowed MIME types for validation
ALLOWED_MIME_TYPES = [
    'text/csv',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
]

class FileValidationError(Exception):
    pass

def save_uploaded_file(uploaded_file, upload_folder: str) -> str:
    """
    Validate and save an uploaded file. Returns the file path.
    Raises FileValidationError on invalid upload.
    """
    if not uploaded_file or not uploaded_file.filename:
        raise FileValidationError("No file selected.")
    if uploaded_file.mimetype not in ALLOWED_MIME_TYPES:
        raise FileValidationError(f"Unsupported file type: {uploaded_file.mimetype}")
    filename = secure_filename(uploaded_file.filename)
    unique_name = f"{uuid.uuid4()}_{filename}"
    os.makedirs(upload_folder, exist_ok=True)
    filepath = os.path.join(upload_folder, unique_name)
    uploaded_file.save(filepath)
    return filepath


def read_location_dataframe(filepath: str) -> pd.DataFrame:
    """
    Read CSV or Excel file into DataFrame.
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext in ('.xls', '.xlsx'):
        return pd.read_excel(filepath)
    else:
        return pd.read_csv(filepath)
