"""Student Route Controller for Personal Attendance and Academic Portal."""

from flask import Blueprint, render_template, request, flash, abort
from flask_login import current_user
from app.utils.decorators import student_required
from app.services.attendance_service import AttendanceService
from app.services.report_service import ReportService
from app.utils.validators import validate_date_range

student_bp = Blueprint('student', __name__, url_prefix='/student')


@student_bp.before_request
def verify_student_profile():
    """Ensure that the authenticated user possesses an active student profile."""
    if current_user.is_authenticated and current_user.is_student:
        if not current_user.student_profile:
            abort(403)


# =========================================================================
# 1. Student Dashboard
# =========================================================================

@student_bp.route('/dashboard')
@student_required
def dashboard():
    """Primary student dashboard with attendance summary, alerts, and subject breakdown."""
    profile = current_user.student_profile
    overall = AttendanceService.get_student_overall_summary(profile)
    subjects_data = AttendanceService.get_student_subject_summaries(profile)
    recent_records = AttendanceService.get_student_attendance_history(profile)[:5]

    return render_template(
        'student/dashboard.html',
        user=current_user,
        profile=profile,
        overall=overall,
        summary=overall,  # For backward-compatibility with template references
        subjects_data=subjects_data,
        recent_records=recent_records
    )


# =========================================================================
# 2. Subject-Wise Attendance Overview
# =========================================================================

@student_bp.route('/attendance')
@student_required
def subject_attendance():
    """Display comprehensive subject-by-subject attendance statistics."""
    profile = current_user.student_profile
    subjects_data = AttendanceService.get_student_subject_summaries(profile)
    overall = AttendanceService.get_student_overall_summary(profile)

    return render_template(
        'student/attendance.html',
        profile=profile,
        subjects=subjects_data['subjects'],
        total_subjects=subjects_data['total_subjects'],
        shortage_count=subjects_data['shortage_count'],
        safe_count=subjects_data['safe_count'],
        threshold=subjects_data['threshold'],
        overall=overall
    )


# =========================================================================
# 3. Individual Subject Attendance Details
# =========================================================================

@student_bp.route('/attendance/<int:subject_id>')
@student_required
def subject_details(subject_id):
    """View session-by-session roll call history for a single curriculum subject."""
    profile = current_user.student_profile
    details = AttendanceService.get_student_subject_details(profile, subject_id)
    if not details:
        abort(404)

    return render_template(
        'student/subject_details.html',
        profile=profile,
        details=details
    )


# =========================================================================
# 4. Chronological Attendance History
# =========================================================================

@student_bp.route('/attendance/history')
@student_required
def attendance_history():
    """Browse historical session attendance records with server-side filtering."""
    profile = current_user.student_profile
    subject_id = request.args.get('subject_id', type=int)
    status = request.args.get('status', '').strip().upper()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    df, dt, d_err = validate_date_range(date_from, date_to)
    if d_err:
        flash(d_err, 'warning')
        date_from = ''
        date_to = ''

    records = AttendanceService.get_student_attendance_history(
        profile,
        subject_id=subject_id,
        date_from=date_from,
        date_to=date_to,
        status=status if status in ('PRESENT', 'ABSENT') else None
    )
    applicable_subjects = AttendanceService.get_student_applicable_subjects(profile)

    return render_template(
        'student/history.html',
        profile=profile,
        records=records,
        applicable_subjects=applicable_subjects,
        filter_subject_id=subject_id,
        filter_status=status,
        filter_date_from=date_from,
        filter_date_to=date_to
    )


# =========================================================================
# 5. "What-If" Future Attendance Simulation Calculator
# =========================================================================

@student_bp.route('/attendance/what-if', methods=['GET', 'POST'])
@student_required
def what_if():
    """Simulate future attendance percentages without altering database records."""
    profile = current_user.student_profile
    applicable_subjects = AttendanceService.get_student_applicable_subjects(profile)

    if request.method == 'POST':
        selected_subject_id = request.form.get('subject_id', type=int)
        upcoming_classes = request.form.get('upcoming_classes', type=int)
    else:
        selected_subject_id = request.args.get('subject_id', type=int)
        upcoming_classes = request.args.get('upcoming_classes', type=int)

    calculation_result = None
    error_message = None

    if selected_subject_id is not None and upcoming_classes is not None:
        calculation_result, error_message = AttendanceService.calculate_what_if_attendance(
            profile,
            selected_subject_id,
            upcoming_classes
        )
        if error_message:
            flash(error_message, 'danger')

    return render_template(
        'student/what_if.html',
        profile=profile,
        applicable_subjects=applicable_subjects,
        selected_subject_id=selected_subject_id,
        upcoming_classes=upcoming_classes if upcoming_classes is not None else 5,
        result=calculation_result,
        error=error_message
    )


# =========================================================================
# 6. Student Academic Profile
# =========================================================================

@student_bp.route('/profile')
@student_required
def profile():
    """Display read-only institutional academic and registration profile."""
    profile_obj = current_user.student_profile
    overall = AttendanceService.get_student_overall_summary(profile_obj)

    return render_template(
        'student/profile.html',
        user=current_user,
        profile=profile_obj,
        overall=overall
    )


# =========================================================================
# 7. Student Personal Attendance CSV Export (Phase 7)
# =========================================================================

@student_bp.route('/attendance/export.csv')
@student_required
def export_attendance_csv():
    """Export the student's personal attendance history as a formula-safe CSV."""
    profile = current_user.student_profile
    subject_id = request.args.get('subject_id', type=int)
    status = request.args.get('status', '').strip().upper()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    df, dt, d_err = validate_date_range(date_from, date_to)
    if d_err:
        date_from = ''
        date_to = ''

    records = AttendanceService.get_student_attendance_history(
        profile,
        subject_id=subject_id,
        date_from=date_from,
        date_to=date_to,
        status=status if status in ('PRESENT', 'ABSENT') else None
    )

    headers = [
        "Session Date", "Period / Slot", "Subject Code", "Subject Name",
        "Class", "Instructor", "Status", "Remarks"
    ]
    rows = [
        [
            rec.session.session_date.strftime('%Y-%m-%d'),
            rec.session.session_slot,
            rec.session.subject.code,
            rec.session.subject.name,
            rec.session.class_group.name,
            rec.session.faculty.full_name if rec.session.faculty else "Staff",
            rec.status,
            rec.remarks or ""
        ]
        for rec in records
    ]

    return ReportService.build_csv_response(
        headers, rows, f"my_attendance_{profile.roll_number}.csv"
    )
