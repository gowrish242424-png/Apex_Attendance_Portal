from flask import Blueprint, render_template, jsonify, current_app
from datetime import datetime, timezone
from app.extensions import db

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Home landing page to verify Flask setup."""
    return render_template(
        'index.html',
        app_name=current_app.config.get('APP_NAME', 'Attendance System'),
        version=current_app.config.get('APP_VERSION', '1.0.0')
    )

@main_bp.route('/health')
def health_check():
    """Health-check endpoint to verify application and database status."""
    db_status = "disconnected"
    try:
        # Perform a lightweight ping to the database engine
        result = db.session.execute(db.text('SELECT 1')).scalar()
        if result == 1:
            db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return jsonify({
        "status": "healthy" if db_status == "connected" else "degraded",
        "app": current_app.config.get('APP_NAME'),
        "version": current_app.config.get('APP_VERSION'),
        "database": db_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "Phase 1 - Project Setup & Health Verification Complete"
    }), 200 if db_status == "connected" else 500
