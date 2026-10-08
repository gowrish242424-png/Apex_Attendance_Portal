"""Input Validation Utilities for Phase 8.

Provides centralized, defensive server-side validation for:
- Text inputs (sanitization, whitespace stripping, length bounds)
- Numeric inputs (IDs, semesters, credits, thresholds)
- Date inputs & chronological date ranges (date_from <= date_to)
- Email and phone contact formats
"""

import re
from datetime import datetime, date

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')
PHONE_REGEX = re.compile(r'^\+?[0-9]{7,15}$')


def validate_string(value, field_name, min_len=1, max_len=255, required=True):
    """Validate and sanitize a string field."""
    if value is None:
        val_str = ""
    else:
        val_str = str(value).strip()

    if required and not val_str:
        return None, f"{field_name} is required."

    if not required and not val_str:
        return "", None

    if len(val_str) < min_len:
        return None, f"{field_name} must be at least {min_len} character(s)."

    if len(val_str) > max_len:
        return None, f"{field_name} cannot exceed {max_len} characters."

    return val_str, None


def validate_id(value, field_name="Identifier"):
    """Validate positive integer ID parameters."""
    if value is None:
        return None, f"{field_name} is required."
    try:
        val_int = int(value)
        if val_int <= 0:
            return None, f"{field_name} must be a positive integer."
        return val_int, None
    except (ValueError, TypeError):
        return None, f"Invalid {field_name} format; expected integer."


def validate_date(date_str, field_name="Date"):
    """Parse and validate date string in YYYY-MM-DD format."""
    if not date_str:
        return None, f"{field_name} is required."
    if isinstance(date_str, date):
        return date_str, None
    try:
        dt = datetime.strptime(str(date_str).strip(), '%Y-%m-%d').date()
        return dt, None
    except (ValueError, TypeError):
        return None, f"Invalid {field_name} format; expected YYYY-MM-DD."


def validate_date_range(date_from_str, date_to_str):
    """Validate date range ensuring both are valid and date_from <= date_to."""
    df = None
    dt = None

    if date_from_str and str(date_from_str).strip():
        df, err = validate_date(date_from_str, "Start Date")
        if err:
            return None, None, err

    if date_to_str and str(date_to_str).strip():
        dt, err = validate_date(date_to_str, "End Date")
        if err:
            return None, None, err

    if df and dt and df > dt:
        return None, None, "Start Date cannot be after End Date."

    return df, dt, None


def validate_threshold(value, default=75.0):
    """Validate attendance cutoff threshold percentage (0.0 to 100.0)."""
    if value is None or str(value).strip() == '':
        return float(default), None
    try:
        th = float(value)
        if th < 0.0 or th > 100.0:
            return None, "Attendance threshold must be between 0% and 100%."
        return round(th, 2), None
    except (ValueError, TypeError):
        return None, "Attendance threshold must be a valid numeric percentage."


def validate_email(email_str):
    """Validate email address format."""
    cleaned, err = validate_string(email_str, "Email", min_len=5, max_len=120, required=True)
    if err:
        return None, err
    cleaned = cleaned.lower()
    if not EMAIL_REGEX.match(cleaned):
        return None, "Invalid email address format."
    return cleaned, None


def validate_phone(phone_str):
    """Validate phone number format (optional field)."""
    if not phone_str or not str(phone_str).strip():
        return None, None
    cleaned = str(phone_str).strip()
    if not PHONE_REGEX.match(cleaned):
        return None, "Invalid phone number format."
    return cleaned, None


def validate_semester(value):
    """Validate academic semester (typically 1 to 10)."""
    val_int, err = validate_id(value, "Semester")
    if err:
        return None, err
    if val_int < 1 or val_int > 10:
        return None, "Semester must be between 1 and 10."
    return val_int, None


def validate_credits(value):
    """Validate subject credits (1 to 12)."""
    val_int, err = validate_id(value, "Credits")
    if err:
        return None, err
    if val_int < 1 or val_int > 12:
        return None, "Course credits must be between 1 and 12."
    return val_int, None
