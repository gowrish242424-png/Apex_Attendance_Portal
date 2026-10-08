from functools import wraps
from flask import abort
from flask_login import current_user, login_required

def admin_required(f):
    """Decorator to restrict route access strictly to Admin users."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def faculty_required(f):
    """Decorator to restrict route access strictly to Faculty members."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_faculty:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def student_required(f):
    """Decorator to restrict route access strictly to Students."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_student:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function
