from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user, login_required
from app.models.user import User

auth_bp = Blueprint('auth', __name__)

def is_safe_url(target):
    """Ensure redirect URL is strictly local to prevent open redirect vulnerabilities."""
    if not target:
        return False
    # Prevent protocol-relative URLs and backslash bypasses (e.g. //evil.com, /\evil.com, \evil.com)
    if target.startswith('//') or target.startswith('/\\') or target.startswith('\\'):
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(target)
    return test_url.scheme in ('', 'http', 'https') and (not test_url.netloc or ref_url.netloc == test_url.netloc)

def get_role_dashboard_url(role):
    """Resolve destination dashboard based on user role."""
    if role == 'admin':
        return url_for('admin.dashboard')
    elif role == 'faculty':
        return url_for('faculty.dashboard')
    elif role == 'student':
        return url_for('student.dashboard')
    return url_for('main.index')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Authenticate users and direct to role-specific dashboards."""
    # If already logged in, redirect to their role dashboard
    if current_user.is_authenticated:
        return redirect(get_role_dashboard_url(current_user.role))

    if request.method == 'POST':
        identifier = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))

        # Input validation
        if not identifier or not password:
            flash("Please enter both username/email and password.", "warning")
            return render_template('auth/login.html', username=identifier), 400

        # Query user by username or email
        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier)
        ).first()

        # Validate credentials
        if user and user.check_password(password):
            if not user.is_active:
                flash("This account has been deactivated. Please contact the administrator.", "danger")
                return render_template('auth/login.html', username=identifier), 403

            # Establish session
            login_user(user, remember=remember)
            flash(f"Welcome back, {user.display_name}!", "success")

            # Check next parameter safely
            next_page = request.args.get('next')
            if next_page and is_safe_url(next_page) and next_page.startswith('/'):
                return redirect(next_page)

            return redirect(get_role_dashboard_url(user.role))

        flash("Invalid username or password. Please try again.", "danger")
        return render_template('auth/login.html', username=identifier), 401

    return render_template('auth/login.html')

@auth_bp.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    """Terminate the authenticated user session."""
    logout_user()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for('auth.login'))
