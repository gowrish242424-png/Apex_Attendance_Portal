"""Faculty Route Controller for Attendance Management Operations."""

from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user
from app.extensions import db
from app.utils.decorators import faculty_required
from app.services.attendance_service import AttendanceService
from app.services.report_service import ReportService
from app.models.attendance import AttendanceSession
from app.models.academic import Class, Subject
from app.utils.validators import validate_id, validate_date, validate_date_range, validate_threshold

faculty_bp = Blueprint('faculty', __name__, url_prefix='/faculty')


@faculty_bp.before_request
def verify_faculty_profile():
    """Ensure that the authenticated user possesses an active faculty profile."""
    if current_user.is_authenticated and current_user.is_faculty:
        if not current_user.faculty_profile:
            abort(403)


# =========================================================================
# 1. Faculty Dashboard
# =========================================================================

@faculty_bp.route('/dashboard')
@faculty_required
def dashboard():
    """Display the primary faculty dashboard with assigned courses and live metrics."""
    profile = current_user.faculty_profile
    assignments = AttendanceService.get_faculty_assignments(profile.id)
    assigned_classes = AttendanceService.get_assigned_classes(profile.id)
    assigned_subjects = AttendanceService.get_assigned_subjects(profile.id)
    recent_sessions = AttendanceService.get_recent_sessions(profile.id, limit=5)
    analytics = AttendanceService.get_faculty_analytics(profile.id)

    return render_template(
        'faculty/dashboard.html',
        user=current_user,
        profile=profile,
        assignments=assignments,
        assigned_classes_count=len(assigned_classes),
        assigned_subjects_count=len(assigned_subjects),
        total_sessions_count=analytics['total_sessions'],
        overall_percentage=analytics['overall_percentage'],
        recent_sessions=recent_sessions
    )


# =========================================================================
# 2. Mark Attendance (Interactive Classroom Roster & Recording)
# =========================================================================

@faculty_bp.route('/attendance/mark', methods=['GET', 'POST'])
@faculty_required
def mark_attendance():
    """Select class, subject, date, slot, and record student attendance."""
    profile = current_user.faculty_profile
    assignments = AttendanceService.get_faculty_assignments(profile.id)

    if request.method == 'POST':
        class_id = request.form.get('class_id')
        subject_id = request.form.get('subject_id')
        date_str = request.form.get('session_date')
        session_slot = request.form.get('session_slot', 'Period 1').strip()

        if not class_id or not subject_id or not date_str:
            flash('Please specify class, subject, and session date.', 'danger')
            return redirect(url_for('faculty.mark_attendance'))

        c_id, c_err = validate_id(class_id, "Class")
        s_id, s_err = validate_id(subject_id, "Subject")
        if c_err or s_err:
            flash(c_err or s_err, 'danger')
            return redirect(url_for('faculty.mark_attendance'))

        # Object-level authorization check: Verify the faculty is assigned to this combo
        assignment = AttendanceService.verify_faculty_assignment(profile.id, c_id, s_id)
        if not assignment:
            abort(403)

        # Parse date defensively
        session_date, dt_err = validate_date(date_str, "Session Date")
        if dt_err:
            flash(dt_err, 'danger')
            return redirect(url_for('faculty.mark_attendance', class_id=class_id, subject_id=subject_id))

        # Check for duplicate session
        existing = AttendanceService.find_session_by_slot(
            c_id, s_id, session_date, session_slot
        )
        if existing:
            flash('Attendance for this class, subject, date and period already exists.', 'warning')
            return redirect(url_for('faculty.edit_attendance', session_id=existing.id))

        # Gather student attendance data
        enrolled = AttendanceService.get_enrolled_students(c_id)
        records_data = []
        for s in enrolled:
            status = request.form.get(f'status_{s.id}', 'PRESENT')
            remarks = request.form.get(f'remarks_{s.id}', '').strip()
            records_data.append({
                'student_id': s.id,
                'status': status,
                'remarks': remarks if remarks else None
            })

        session_obj, error = AttendanceService.create_attendance_session(
            profile.id, c_id, s_id, session_date, session_slot, records_data
        )

        if error:
            flash(error, 'danger')
            return redirect(url_for('faculty.mark_attendance', class_id=class_id, subject_id=subject_id))

        flash(f'Attendance saved successfully for {len(records_data)} students.', 'success')
        return redirect(url_for('faculty.attendance_history'))

    # GET Request: Roster selection and student display
    selected_class_id = request.args.get('class_id', type=int)
    selected_subject_id = request.args.get('subject_id', type=int)
    date_str = request.args.get('session_date', date.today().isoformat())
    session_slot = request.args.get('session_slot', 'Period 1')

    selected_class = None
    selected_subject = None
    enrolled_students = []
    existing_session = None

    if selected_class_id and selected_subject_id:
        # Object-level authorization check: Must belong to current faculty's assignments
        assignment = AttendanceService.verify_faculty_assignment(profile.id, selected_class_id, selected_subject_id)
        if not assignment:
            abort(403)

        selected_class = assignment.class_group
        selected_subject = assignment.subject

        # Parse date safely
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            target_date = date.today()
            date_str = target_date.isoformat()

        # Check if session is already recorded
        existing_session = AttendanceService.find_session_by_slot(
            selected_class_id, selected_subject_id, target_date, session_slot
        )

        if not existing_session:
            enrolled_students = AttendanceService.get_enrolled_students(selected_class_id)

    return render_template(
        'faculty/mark_attendance.html',
        profile=profile,
        assignments=assignments,
        selected_class_id=selected_class_id,
        selected_subject_id=selected_subject_id,
        selected_class=selected_class,
        selected_subject=selected_subject,
        session_date=date_str,
        session_slot=session_slot,
        enrolled_students=enrolled_students,
        existing_session=existing_session,
        today_iso=date.today().isoformat()
    )


# =========================================================================
# 3. Edit Attendance
# =========================================================================

@faculty_bp.route('/attendance/<int:session_id>/edit', methods=['GET', 'POST'])
@faculty_required
def edit_attendance(session_id):
    """View and modify student attendance records for an existing session."""
    profile = current_user.faculty_profile
    session_obj = db.session.get(AttendanceSession, session_id)
    if not session_obj:
        abort(404)

    # Object-level authorization check: Faculty can only edit their own sessions
    if session_obj.faculty_id != profile.id:
        abort(403)

    if request.method == 'POST':
        records_data = []
        for rec in session_obj.records:
            status = request.form.get(f'status_{rec.student_id}', rec.status)
            remarks = request.form.get(f'remarks_{rec.student_id}', rec.remarks or '').strip()
            records_data.append({
                'student_id': rec.student_id,
                'status': status,
                'remarks': remarks if remarks else None
            })

        success, msg = AttendanceService.update_attendance_session(session_obj, records_data)
        if success:
            flash(msg, 'success')
            return redirect(url_for('faculty.attendance_history'))
        else:
            flash(msg, 'danger')

    return render_template(
        'faculty/edit_attendance.html',
        profile=profile,
        session=session_obj
    )


# =========================================================================
# 4. Attendance History
# =========================================================================

@faculty_bp.route('/attendance/history')
@faculty_required
def attendance_history():
    """Browse historical attendance sessions conducted exclusively by this faculty."""
    profile = current_user.faculty_profile
    class_id = request.args.get('class_id', type=int)
    subject_id = request.args.get('subject_id', type=int)
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    df, dt, d_err = validate_date_range(date_from, date_to)
    if d_err:
        flash(d_err, 'warning')
        date_from = ''
        date_to = ''

    sessions = AttendanceService.get_sessions_history(
        profile.id,
        class_id=class_id,
        subject_id=subject_id,
        date_from=date_from,
        date_to=date_to
    )

    assigned_classes = AttendanceService.get_assigned_classes(profile.id)
    assigned_subjects = AttendanceService.get_assigned_subjects(profile.id)

    return render_template(
        'faculty/history.html',
        profile=profile,
        sessions=sessions,
        assigned_classes=assigned_classes,
        assigned_subjects=assigned_subjects,
        filter_class_id=class_id,
        filter_subject_id=subject_id,
        filter_date_from=date_from,
        filter_date_to=date_to
    )


# =========================================================================
# 5. Attendance Analytics
# =========================================================================

@faculty_bp.route('/attendance/analytics')
@faculty_required
def attendance_analytics():
    """Display comprehensive attendance statistics, subject, and class breakdown."""
    profile = current_user.faculty_profile
    analytics_data = AttendanceService.get_faculty_analytics(profile.id)

    return render_template(
        'faculty/analytics.html',
        profile=profile,
        analytics=analytics_data
    )


# =========================================================================
# 6. Defaulters List
# =========================================================================

@faculty_bp.route('/attendance/defaulters')
@faculty_required
def attendance_defaulters():
    """Display enrolled students below the institutional attendance threshold."""
    profile = current_user.faculty_profile
    class_id = request.args.get('class_id', type=int)
    subject_id = request.args.get('subject_id', type=int)
    raw_thresh = request.args.get('threshold')
    custom_threshold = None
    if raw_thresh is not None and str(raw_thresh).strip() != '':
        th_val, th_err = validate_threshold(raw_thresh)
        if th_err:
            flash(th_err, 'warning')
        else:
            custom_threshold = th_val

    defaulters, threshold = AttendanceService.get_faculty_defaulters(
        profile.id,
        class_id=class_id,
        subject_id=subject_id,
        custom_threshold=custom_threshold
    )

    assigned_classes = AttendanceService.get_assigned_classes(profile.id)
    assigned_subjects = AttendanceService.get_assigned_subjects(profile.id)

    return render_template(
        'faculty/defaulters.html',
        profile=profile,
        defaulters=defaulters,
        threshold=threshold,
        assigned_classes=assigned_classes,
        assigned_subjects=assigned_subjects,
        filter_class_id=class_id,
        filter_subject_id=subject_id
    )


# =========================================================================
# 7. Faculty Comprehensive Reports & CSV Exports (Phase 7)
# =========================================================================

@faculty_bp.route('/reports')
@faculty_required
def reports():
    """Faculty attendance reports dashboard strictly within assigned scope."""
    profile = current_user.faculty_profile
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    df, dt, d_err = validate_date_range(date_from, date_to)
    if d_err:
        flash(d_err, 'warning')
        date_from = ''
        date_to = ''

    reporting_data = ReportService.get_faculty_reporting_data(profile.id, date_from, date_to)

    return render_template(
        'faculty/reports.html',
        profile=profile,
        data=reporting_data,
        date_from=date_from,
        date_to=date_to
    )


@faculty_bp.route('/reports/attendance/export.csv')
@faculty_required
def export_attendance_csv():
    """Export attendance performance summary for courses taught by authenticated faculty."""
    profile = current_user.faculty_profile
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    df, dt, d_err = validate_date_range(date_from, date_to)
    if d_err:
        date_from = ''
        date_to = ''

    reporting_data = ReportService.get_faculty_reporting_data(profile.id, date_from, date_to)

    headers = [
        "Class", "Subject Code", "Subject Name", "Sessions Conducted",
        "Present Count", "Absent Count", "Attendance Rate %", "Status"
    ]
    rows = [
        [
            item['class'].name,
            item['subject'].code,
            item['subject'].name,
            item['sessions_count'],
            item['present_count'],
            item['absent_count'],
            item['percentage'],
            item['status']
        ]
        for item in reporting_data['subject_breakdown']
    ]

    return ReportService.build_csv_response(
        headers, rows, f"faculty_{profile.employee_id}_attendance_report.csv"
    )


@faculty_bp.route('/reports/defaulters/export.csv')
@faculty_required
def export_defaulters_csv():
    """Export attendance defaulters list strictly within authenticated faculty's scope."""
    profile = current_user.faculty_profile
    reporting_data = ReportService.get_faculty_reporting_data(profile.id)

    headers = [
        "Roll Number", "Student Name", "Class", "Subject Code",
        "Subject Name", "Attended", "Total Sessions", "Turnout %",
        "Required Cutoff %", "Shortage %"
    ]
    rows = [
        [
            item['student'].roll_number,
            item['student'].full_name,
            item['class'].name,
            item['subject'].code,
            item['subject'].name,
            item['attended'],
            item['total'],
            item['percentage'],
            item['threshold'],
            item['shortage']
        ]
        for item in reporting_data['defaulters']
    ]

    return ReportService.build_csv_response(
        headers, rows, f"faculty_{profile.employee_id}_defaulters_report.csv"
    )
