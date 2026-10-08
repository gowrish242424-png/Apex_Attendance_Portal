"""CSRF Protection Utility for Phase 8.

Implements cryptographically secure, session-bound CSRF token generation
and validation for state-changing HTTP requests without third-party dependencies.
"""

import hmac
import secrets
from flask import session, request, abort, current_app


def generate_csrf():
    """Generate or retrieve a cryptographically secure CSRF token for the current session."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


# Alias for compatibility
generate_csrf_token = generate_csrf


def validate_csrf():
    """Verify CSRF token on state-changing HTTP requests.
    
    Safe HTTP methods (GET, HEAD, OPTIONS, TRACE) are bypassed.
    Bypassed during testing or when WTF_CSRF_ENABLED is False.
    """
    if not current_app.config.get('WTF_CSRF_ENABLED', True):
        return

    if request.method in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
        return

    token = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
    expected = session.get('_csrf_token')

    if not token or not expected or not hmac.compare_digest(token, expected):
        abort(400, description="CSRF validation failed: Token missing or invalid.")
