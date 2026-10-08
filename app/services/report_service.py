"""Reporting and Institutional Analytics Service.

Provides data aggregation, filtering, trend calculation, and formula-safe CSV export
for Administrator, Faculty, and Student reporting domains.
"""

import csv
import io
import math
from datetime import date, datetime
from flask import Response
from sqlalchemy import func
from app.extensions import db
from app.models.academic import Department, Class, Subject, FacultyAssignment
from app.models.user import User, StudentProfile, FacultyProfile
from app.models.attendance import AttendanceSession, AttendanceRecord
from app.models.settings import SystemSetting


class ReportService:
    """Service layer governing institutional attendance reporting and data exports."""

    # =========================================================================
    # 1. Formula Injection Protection & CSV Helpers
    # =========================================================================

    @staticmethod
    def sanitize_csv_cell(value):
        """Neutralize potential CSV formula injection (DDE/Formula exploit).
        
        Prepends a single quote to string values starting with '=', '+', '-', '@', '\\t', '\\r'
        unless the value is a legitimate numeric literal.
        """
        if value is None:
            return ""
        val_str = str(value)
        if not val_str:
            return ""

        # Check if first character is a formula trigger
        if val_str[0] in ('=', '+', '-', '@', '\t', '\r'):
            # Allow pure numeric values like -5, -25.5, +10
            try:
                float(val_str)
                return val_str
            except ValueError:
                # String starts with formula trigger: escape with leading quote
                return "'" + val_str
        return val_str

    @staticmethod
    def build_csv_response(headers, rows, filename):
        """Generate a streaming UTF-8 CSV Flask Response with proper headers."""
        output = io.StringIO()
        # Use excel dialect with standard quoting
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

        # Write sanitized header
        writer.writerow([ReportService.sanitize_csv_cell(h) for h in headers])

        # Write sanitized rows
        for row in rows:
            writer.writerow([ReportService.sanitize_csv_cell(cell) for cell in row])

        csv_data = output.getvalue()
        output.close()

        # Add UTF-8 BOM so Excel opens non-ASCII characters without distortion
        bom_csv_data = '\ufeff' + csv_data

        return Response(
            bom_csv_data,
            mimetype='text/csv; charset=utf-8',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': 'text/csv; charset=utf-8'
            }
        )

    # =========================================================================
    # 2. Institutional Analytics (Admin)
    # =========================================================================

    @staticmethod
    def get_institutional_analytics():
        """Compute institutional metrics, department/class summaries, and trend data."""
        threshold = float(SystemSetting.get_int('min_attendance_threshold', default=75))

        total_departments = Department.query.count()
        total_classes = Class.query.count()
        total_subjects = Subject.query.count()
        total_faculty = User.query.filter_by(role='faculty', is_active=True).count()
        total_students = User.query.filter_by(role='student', is_active=True).count()
        total_sessions = AttendanceSession.query.count()
        total_records = AttendanceRecord.query.count()

        present_count = AttendanceRecord.query.filter_by(status='PRESENT').count()
        absent_count = AttendanceRecord.query.filter_by(status='ABSENT').count()
        overall_percentage = (
            round((present_count / total_records) * 100, 2)
            if total_records > 0 else 0.0
        )

        # Student threshold distribution
        active_student_profiles = (
            StudentProfile.query
            .join(User)
            .filter(User.is_active.is_(True))
            .all()
        )

        eligible_students_count = 0
        defaulter_students_count = 0
        unrecorded_students_count = 0

        for sp in active_student_profiles:
            st_records = AttendanceRecord.query.filter_by(student_id=sp.id).all()
            if not st_records:
                unrecorded_students_count += 1
            else:
                st_present = sum(1 for r in st_records if r.status == 'PRESENT')
                pct = (st_present / len(st_records)) * 100
                if pct >= threshold:
                    eligible_students_count += 1
                else:
                    defaulter_students_count += 1

        # Department breakdown
        departments = Department.query.order_by(Department.code.asc()).all()
        dept_breakdown = []
        for dept in departments:
            # All classes in department
            class_ids = [c.id for c in dept.classes]
            dept_students_count = len(dept.students)

            if class_ids:
                session_ids = [
                    s.id for s in AttendanceSession.query.filter(AttendanceSession.class_id.in_(class_ids)).all()
                ]
                sessions_count = len(session_ids)
                if session_ids:
                    records = AttendanceRecord.query.filter(AttendanceRecord.session_id.in_(session_ids)).all()
                    dept_total = len(records)
                    dept_present = sum(1 for r in records if r.status == 'PRESENT')
                    dept_absent = dept_total - dept_present
                else:
                    dept_total = 0
                    dept_present = 0
                    dept_absent = 0
            else:
                sessions_count = 0
                dept_total = 0
                dept_present = 0
                dept_absent = 0

            dept_pct = round((dept_present / dept_total) * 100, 2) if dept_total > 0 else 0.0
            dept_breakdown.append({
                'department': dept,
                'students_count': dept_students_count,
                'sessions_count': sessions_count,
                'total_records': dept_total,
                'present_count': dept_present,
                'absent_count': dept_absent,
                'percentage': dept_pct
            })

        # Class breakdown
        classes = Class.query.order_by(Class.name.asc()).all()
        class_breakdown = []
        for cls in classes:
            c_sessions = AttendanceSession.query.filter_by(class_id=cls.id).all()
            c_session_ids = [s.id for s in c_sessions]
            c_sessions_count = len(c_sessions)

            if c_session_ids:
                c_records = AttendanceRecord.query.filter(AttendanceRecord.session_id.in_(c_session_ids)).all()
                c_total = len(c_records)
                c_present = sum(1 for r in c_records if r.status == 'PRESENT')
                c_absent = c_total - c_present
            else:
                c_total = 0
                c_present = 0
                c_absent = 0

            c_pct = round((c_present / c_total) * 100, 2) if c_total > 0 else 0.0
            class_breakdown.append({
                'class': cls,
                'students_count': len(cls.students),
                'sessions_count': c_sessions_count,
                'total_records': c_total,
                'present_count': c_present,
                'absent_count': c_absent,
                'percentage': c_pct
            })

        # Attendance trend by date (chronological)
        trend_data = ReportService.get_attendance_trends()

        return {
            'total_departments': total_departments,
            'total_classes': total_classes,
            'total_subjects': total_subjects,
            'total_faculty': total_faculty,
            'total_students': total_students,
            'total_sessions': total_sessions,
            'total_records': total_records,
            'present_count': present_count,
            'absent_count': absent_count,
            'overall_percentage': overall_percentage,
            'threshold': threshold,
            'eligible_students_count': eligible_students_count,
            'defaulter_students_count': defaulter_students_count,
            'unrecorded_students_count': unrecorded_students_count,
            'department_breakdown': dept_breakdown,
            'class_breakdown': class_breakdown,
            'trend_data': trend_data,
        }

    # =========================================================================
    # 3. Attendance Trend Analysis
    # =========================================================================

    @staticmethod
    def get_attendance_trends(department_id=None, class_id=None, subject_id=None, date_from=None, date_to=None):
        """Aggregate daily attendance volume and turnout percentages for visualization."""
        query = AttendanceSession.query

        if class_id:
            try:
                query = query.filter(AttendanceSession.class_id == int(class_id))
            except (ValueError, TypeError):
                pass
        elif department_id:
            try:
                dept_classes = [c.id for c in Class.query.filter_by(department_id=int(department_id)).all()]
                query = query.filter(AttendanceSession.class_id.in_(dept_classes))
            except (ValueError, TypeError):
                pass

        if subject_id:
            try:
                query = query.filter(AttendanceSession.subject_id == int(subject_id))
            except (ValueError, TypeError):
                pass

        if date_from:
            if isinstance(date_from, str) and date_from.strip():
                try:
                    df = datetime.strptime(date_from.strip(), '%Y-%m-%d').date()
                    query = query.filter(AttendanceSession.session_date >= df)
                except ValueError:
                    pass
            elif isinstance(date_from, date):
                query = query.filter(AttendanceSession.session_date >= date_from)

        if date_to:
            if isinstance(date_to, str) and date_to.strip():
                try:
                    dt = datetime.strptime(date_to.strip(), '%Y-%m-%d').date()
                    query = query.filter(AttendanceSession.session_date <= dt)
                except ValueError:
                    pass
            elif isinstance(date_to, date):
                query = query.filter(AttendanceSession.session_date <= date_to)

        sessions = query.order_by(AttendanceSession.session_date.asc()).all()
        if not sessions:
            return {'labels': [], 'rates': [], 'presents': [], 'absents': [], 'sessions_count': 0}

        # Group by date
        daily_data = {}
        for s in sessions:
            d_str = s.session_date.strftime('%Y-%m-%d')
            if d_str not in daily_data:
                daily_data[d_str] = {'present': 0, 'absent': 0, 'total': 0}
            daily_data[d_str]['present'] += s.present_count
            daily_data[d_str]['absent'] += s.absent_count
            daily_data[d_str]['total'] += s.total_students

        labels = []
        rates = []
        presents = []
        absents = []

        for d_str in sorted(daily_data.keys()):
            labels.append(d_str)
            item = daily_data[d_str]
            rate = round((item['present'] / item['total']) * 100, 2) if item['total'] > 0 else 0.0
            rates.append(rate)
            presents.append(item['present'])
            absents.append(item['absent'])

        return {
            'labels': labels,
            'rates': rates,
            'presents': presents,
            'absents': absents,
            'sessions_count': len(sessions)
        }

    # =========================================================================
    # 4. Class Attendance Report
    # =========================================================================

    @staticmethod
    def get_class_attendance_report(department_id=None, class_id=None, date_from=None, date_to=None):
        """Aggregate attendance metrics per class, with optional detailed student roster."""
        query = Class.query

        if department_id:
            try:
                query = query.filter(Class.department_id == int(department_id))
            except (ValueError, TypeError):
                pass

        if class_id:
            try:
                query = query.filter(Class.id == int(class_id))
            except (ValueError, TypeError):
                pass

        classes = query.order_by(Class.name.asc()).all()
        threshold = float(SystemSetting.get_int('min_attendance_threshold', default=75))

        classes_data = []
        student_details = []

        for cls in classes:
            # Session query with date filtering
            s_query = AttendanceSession.query.filter_by(class_id=cls.id)
            if date_from:
                try:
                    df = datetime.strptime(date_from.strip(), '%Y-%m-%d').date() if isinstance(date_from, str) else date_from
                    s_query = s_query.filter(AttendanceSession.session_date >= df)
                except ValueError:
                    pass
            if date_to:
                try:
                    dt = datetime.strptime(date_to.strip(), '%Y-%m-%d').date() if isinstance(date_to, str) else date_to
                    s_query = s_query.filter(AttendanceSession.session_date <= dt)
                except ValueError:
                    pass

            sessions = s_query.all()
            session_ids = [s.id for s in sessions]

            if session_ids:
                records = AttendanceRecord.query.filter(AttendanceRecord.session_id.in_(session_ids)).all()
                total = len(records)
                present = sum(1 for r in records if r.status == 'PRESENT')
                absent = total - present
            else:
                records = []
                total = 0
                present = 0
                absent = 0

            pct = round((present / total) * 100, 2) if total > 0 else 0.0

            classes_data.append({
                'class': cls,
                'students_count': len(cls.students),
                'sessions_count': len(sessions),
                'total_records': total,
                'present_count': present,
                'absent_count': absent,
                'percentage': pct,
                'status': 'Good' if pct >= threshold else ('Shortage' if total > 0 else 'No Sessions')
            })

            # If a specific class was filtered, build student-level roster
            if class_id or len(classes) == 1:
                enrolled_students = (
                    StudentProfile.query
                    .filter_by(class_id=cls.id)
                    .order_by(StudentProfile.roll_number.asc())
                    .all()
                )
                for stud in enrolled_students:
                    st_records = [r for r in records if r.student_id == stud.id]
                    st_total = len(st_records)
                    st_present = sum(1 for r in st_records if r.status == 'PRESENT')
                    st_absent = st_total - st_present
                    st_pct = round((st_present / st_total) * 100, 2) if st_total > 0 else 0.0

                    student_details.append({
                        'student': stud,
                        'class': cls,
                        'total': st_total,
                        'present': st_present,
                        'absent': st_absent,
                        'percentage': st_pct,
                        'is_shortage': (st_total > 0 and st_pct < threshold),
                        'status': 'Good' if st_pct >= threshold else ('Shortage' if st_total > 0 else 'Not Started')
                    })

        return {
            'classes_data': classes_data,
            'student_details': student_details,
            'threshold': threshold
        }

    # =========================================================================
    # 5. Subject Attendance Report
    # =========================================================================

    @staticmethod
    def get_subject_attendance_report(department_id=None, class_id=None, subject_id=None, date_from=None, date_to=None):
        """Aggregate attendance metrics per curriculum subject with student roll call breakdown."""
        query = Subject.query

        if department_id:
            try:
                query = query.filter(Subject.department_id == int(department_id))
            except (ValueError, TypeError):
                pass

        if subject_id:
            try:
                query = query.filter(Subject.id == int(subject_id))
            except (ValueError, TypeError):
                pass

        subjects = query.order_by(Subject.code.asc()).all()
        threshold = float(SystemSetting.get_int('min_attendance_threshold', default=75))

        subjects_data = []
        student_details = []

        for sub in subjects:
            s_query = AttendanceSession.query.filter_by(subject_id=sub.id)

            if class_id:
                try:
                    s_query = s_query.filter(AttendanceSession.class_id == int(class_id))
                except (ValueError, TypeError):
                    pass

            if date_from:
                try:
                    df = datetime.strptime(date_from.strip(), '%Y-%m-%d').date() if isinstance(date_from, str) else date_from
                    s_query = s_query.filter(AttendanceSession.session_date >= df)
                except ValueError:
                    pass

            if date_to:
                try:
                    dt = datetime.strptime(date_to.strip(), '%Y-%m-%d').date() if isinstance(date_to, str) else date_to
                    s_query = s_query.filter(AttendanceSession.session_date <= dt)
                except ValueError:
                    pass

            sessions = s_query.all()
            session_ids = [s.id for s in sessions]

            if session_ids:
                records = AttendanceRecord.query.filter(AttendanceRecord.session_id.in_(session_ids)).all()
                total = len(records)
                present = sum(1 for r in records if r.status == 'PRESENT')
                absent = total - present
            else:
                records = []
                total = 0
                present = 0
                absent = 0

            pct = round((present / total) * 100, 2) if total > 0 else 0.0

            subjects_data.append({
                'subject': sub,
                'sessions_count': len(sessions),
                'total_records': total,
                'present_count': present,
                'absent_count': absent,
                'percentage': pct,
                'status': 'Good' if pct >= threshold else ('Shortage' if total > 0 else 'No Sessions')
            })

            # If a specific subject was filtered, build student roll call roster
            if subject_id or len(subjects) == 1:
                # Find distinct students evaluated in these sessions
                eval_student_ids = sorted(list({r.student_id for r in records}))
                students = StudentProfile.query.filter(StudentProfile.id.in_(eval_student_ids)).all() if eval_student_ids else []

                for stud in students:
                    st_records = [r for r in records if r.student_id == stud.id]
                    st_total = len(st_records)
                    st_present = sum(1 for r in st_records if r.status == 'PRESENT')
                    st_absent = st_total - st_present
                    st_pct = round((st_present / st_total) * 100, 2) if st_total > 0 else 0.0

                    student_details.append({
                        'student': stud,
                        'subject': sub,
                        'total': st_total,
                        'present': st_present,
                        'absent': st_absent,
                        'percentage': st_pct,
                        'is_shortage': (st_total > 0 and st_pct < threshold),
                        'status': 'Good' if st_pct >= threshold else ('Shortage' if st_total > 0 else 'Not Started')
                    })

        return {
            'subjects_data': subjects_data,
            'student_details': student_details,
            'threshold': threshold
        }

    # =========================================================================
    # 6. Faculty Activity Report
    # =========================================================================

    @staticmethod
    def get_faculty_activity_report(department_id=None, faculty_id=None, date_from=None, date_to=None):
        """Inspect instructional sessions and attendance logs per faculty member."""
        query = FacultyProfile.query

        if department_id:
            try:
                query = query.filter(FacultyProfile.department_id == int(department_id))
            except (ValueError, TypeError):
                pass

        if faculty_id:
            try:
                query = query.filter(FacultyProfile.id == int(faculty_id))
            except (ValueError, TypeError):
                pass

        faculty_members = query.order_by(FacultyProfile.full_name.asc()).all()
        activity_data = []

        for fac in faculty_members:
            s_query = AttendanceSession.query.filter_by(faculty_id=fac.id)

            if date_from:
                try:
                    df = datetime.strptime(date_from.strip(), '%Y-%m-%d').date() if isinstance(date_from, str) else date_from
                    s_query = s_query.filter(AttendanceSession.session_date >= df)
                except ValueError:
                    pass

            if date_to:
                try:
                    dt = datetime.strptime(date_to.strip(), '%Y-%m-%d').date() if isinstance(date_to, str) else date_to
                    s_query = s_query.filter(AttendanceSession.session_date <= dt)
                except ValueError:
                    pass

            sessions = s_query.all()
            session_ids = [s.id for s in sessions]

            if session_ids:
                records = AttendanceRecord.query.filter(AttendanceRecord.session_id.in_(session_ids)).all()
                total_records = len(records)
                present_count = sum(1 for r in records if r.status == 'PRESENT')
                avg_turnout = round((present_count / total_records) * 100, 2) if total_records > 0 else 0.0
            else:
                total_records = 0
                present_count = 0
                avg_turnout = 0.0

            # Assigned unique classes and subjects
            assigned_classes = {a.class_group.name for a in fac.assignments if a.class_group}
            assigned_subjects = {a.subject.code for a in fac.assignments if a.subject}

            activity_data.append({
                'faculty': fac,
                'assigned_classes_list': sorted(list(assigned_classes)),
                'assigned_subjects_list': sorted(list(assigned_subjects)),
                'sessions_conducted': len(sessions),
                'total_records': total_records,
                'present_count': present_count,
                'average_turnout': avg_turnout
            })

        return activity_data

    # =========================================================================
    # 7. Student Attendance Report (Admin Global View)
    # =========================================================================

    @staticmethod
    def get_student_attendance_report(search=None, department_id=None, class_id=None, subject_id=None):
        """Search and filter student attendance across departments, classes, or specific subjects."""
        query = StudentProfile.query.join(User).filter(User.is_active.is_(True))

        if search and search.strip():
            kw = f"%{search.strip()}%"
            query = query.filter(
                (StudentProfile.full_name.ilike(kw)) |
                (StudentProfile.roll_number.ilike(kw)) |
                (User.email.ilike(kw))
            )

        if department_id:
            try:
                query = query.filter(StudentProfile.department_id == int(department_id))
            except (ValueError, TypeError):
                pass

        if class_id:
            try:
                query = query.filter(StudentProfile.class_id == int(class_id))
            except (ValueError, TypeError):
                pass

        students = query.order_by(StudentProfile.roll_number.asc()).all()
        threshold = float(SystemSetting.get_int('min_attendance_threshold', default=75))
        report_data = []

        sub_filter = None
        if subject_id:
            try:
                sub_filter = int(subject_id)
            except (ValueError, TypeError):
                pass

        for stud in students:
            if sub_filter:
                # Query specific subject records
                records = (
                    AttendanceRecord.query
                    .join(AttendanceSession)
                    .filter(
                        AttendanceRecord.student_id == stud.id,
                        AttendanceSession.subject_id == sub_filter
                    )
                    .all()
                )
                subject_obj = db.session.get(Subject, sub_filter)
                sub_name = f"{subject_obj.code} ({subject_obj.name})" if subject_obj else "Selected Subject"
            else:
                # Overall records across all courses
                records = AttendanceRecord.query.filter_by(student_id=stud.id).all()
                sub_name = "All Curriculum Subjects"

            total = len(records)
            present = sum(1 for r in records if r.status == 'PRESENT')
            absent = total - present
            pct = round((present / total) * 100, 2) if total > 0 else 0.0
            is_shortage = (total > 0 and pct < threshold)

            report_data.append({
                'student': stud,
                'subject_label': sub_name,
                'total': total,
                'present': present,
                'absent': absent,
                'percentage': pct,
                'threshold': threshold,
                'is_shortage': is_shortage,
                'status': 'Good' if pct >= threshold else ('Shortage' if total > 0 else 'Not Started')
            })

        return report_data, threshold

    # =========================================================================
    # 8. Institutional Defaulters Report
    # =========================================================================

    @staticmethod
    def get_institutional_defaulters_report(department_id=None, class_id=None, subject_id=None, custom_threshold=None):
        """Identify all students across the institution whose attendance falls below cutoff."""
        if custom_threshold is not None:
            threshold = float(custom_threshold)
        else:
            threshold = float(SystemSetting.get_int('min_attendance_threshold', default=75))

        # Query relevant sessions
        s_query = AttendanceSession.query

        if class_id:
            try:
                s_query = s_query.filter(AttendanceSession.class_id == int(class_id))
            except (ValueError, TypeError):
                pass
        elif department_id:
            try:
                dept_class_ids = [c.id for c in Class.query.filter_by(department_id=int(department_id)).all()]
                s_query = s_query.filter(AttendanceSession.class_id.in_(dept_class_ids))
            except (ValueError, TypeError):
                pass

        if subject_id:
            try:
                s_query = s_query.filter(AttendanceSession.subject_id == int(subject_id))
            except (ValueError, TypeError):
                pass

        sessions = s_query.all()
        if not sessions:
            return [], threshold

        # Group sessions by (class_id, subject_id)
        grouped_sessions = {}
        for s in sessions:
            pair = (s.class_id, s.subject_id)
            if pair not in grouped_sessions:
                grouped_sessions[pair] = []
            grouped_sessions[pair].append(s.id)

        defaulters = []

        for (cid, sid), sess_ids in grouped_sessions.items():
            cls_obj = db.session.get(Class, cid)
            sub_obj = db.session.get(Subject, sid)
            enrolled_students = StudentProfile.query.filter_by(class_id=cid).all()

            for stud in enrolled_students:
                records = (
                    AttendanceRecord.query
                    .filter(
                        AttendanceRecord.session_id.in_(sess_ids),
                        AttendanceRecord.student_id == stud.id
                    )
                    .all()
                )
                total = len(records)
                if total == 0:
                    continue

                present = sum(1 for r in records if r.status == 'PRESENT')
                pct = round((present / total) * 100, 2)

                if pct < threshold:
                    defaulters.append({
                        'student': stud,
                        'class': cls_obj,
                        'subject': sub_obj,
                        'attended': present,
                        'total': total,
                        'percentage': pct,
                        'threshold': threshold,
                        'shortage': round(threshold - pct, 2)
                    })

        defaulters.sort(key=lambda d: d['percentage'])
        return defaulters, threshold

    # =========================================================================
    # 9. Faculty Reporting Data (Scoped strictly to faculty_id)
    # =========================================================================

    @staticmethod
    def get_faculty_reporting_data(faculty_id, date_from=None, date_to=None):
        """Retrieve aggregated attendance reports and trends strictly for this faculty's scope."""
        threshold = float(SystemSetting.get_int('min_attendance_threshold', default=75))

        # Query faculty's conducted sessions
        s_query = AttendanceSession.query.filter_by(faculty_id=faculty_id)

        if date_from:
            try:
                df = datetime.strptime(date_from.strip(), '%Y-%m-%d').date() if isinstance(date_from, str) else date_from
                s_query = s_query.filter(AttendanceSession.session_date >= df)
            except ValueError:
                pass

        if date_to:
            try:
                dt = datetime.strptime(date_to.strip(), '%Y-%m-%d').date() if isinstance(date_to, str) else date_to
                s_query = s_query.filter(AttendanceSession.session_date <= dt)
            except ValueError:
                pass

        sessions = s_query.order_by(AttendanceSession.session_date.desc()).all()
        session_ids = [s.id for s in sessions]

        if session_ids:
            records = AttendanceRecord.query.filter(AttendanceRecord.session_id.in_(session_ids)).all()
            total_records = len(records)
            present_count = sum(1 for r in records if r.status == 'PRESENT')
            absent_count = total_records - present_count
        else:
            records = []
            total_records = 0
            present_count = 0
            absent_count = 0

        overall_pct = round((present_count / total_records) * 100, 2) if total_records > 0 else 0.0

        # Faculty assignments
        assignments = FacultyAssignment.query.filter_by(faculty_id=faculty_id).all()
        subject_breakdown = []
        for assign in assignments:
            sub = assign.subject
            sub_sessions = [s for s in sessions if s.subject_id == sub.id and s.class_id == assign.class_id]
            sub_sess_ids = [s.id for s in sub_sessions]

            if sub_sess_ids:
                sub_records = [r for r in records if r.session_id in sub_sess_ids]
                sub_total = len(sub_records)
                sub_present = sum(1 for r in sub_records if r.status == 'PRESENT')
                sub_absent = sub_total - sub_present
            else:
                sub_total = 0
                sub_present = 0
                sub_absent = 0

            sub_pct = round((sub_present / sub_total) * 100, 2) if sub_total > 0 else 0.0

            subject_breakdown.append({
                'assignment': assign,
                'class': assign.class_group,
                'subject': sub,
                'sessions_count': len(sub_sessions),
                'total_records': sub_total,
                'present_count': sub_present,
                'absent_count': sub_absent,
                'percentage': sub_pct,
                'status': 'Good' if sub_pct >= threshold else ('Shortage' if sub_total > 0 else 'No Sessions')
            })

        # Defaulters within faculty scope
        defaulters = []
        for item in subject_breakdown:
            cls_obj = item['class']
            sub_obj = item['subject']
            sub_sess_ids = [s.id for s in sessions if s.subject_id == sub_obj.id and s.class_id == cls_obj.id]
            if not sub_sess_ids:
                continue

            enrolled = StudentProfile.query.filter_by(class_id=cls_obj.id).all()
            for stud in enrolled:
                st_records = [r for r in records if r.session_id in sub_sess_ids and r.student_id == stud.id]
                st_total = len(st_records)
                if st_total == 0:
                    continue

                st_present = sum(1 for r in st_records if r.status == 'PRESENT')
                st_pct = round((st_present / st_total) * 100, 2)
                if st_pct < threshold:
                    defaulters.append({
                        'student': stud,
                        'class': cls_obj,
                        'subject': sub_obj,
                        'attended': st_present,
                        'total': st_total,
                        'percentage': st_pct,
                        'threshold': threshold,
                        'shortage': round(threshold - st_pct, 2)
                    })

        defaulters.sort(key=lambda d: d['percentage'])

        # Trends for faculty
        daily_trends = {}
        for s in reversed(sessions):
            d_str = s.session_date.strftime('%Y-%m-%d')
            if d_str not in daily_trends:
                daily_trends[d_str] = {'present': 0, 'total': 0}
            daily_trends[d_str]['present'] += s.present_count
            daily_trends[d_str]['total'] += s.total_students

        trend_labels = list(daily_trends.keys())
        trend_rates = [
            round((daily_trends[d]['present'] / daily_trends[d]['total']) * 100, 2) if daily_trends[d]['total'] > 0 else 0.0
            for d in trend_labels
        ]

        return {
            'total_sessions': len(sessions),
            'total_records': total_records,
            'present_count': present_count,
            'absent_count': absent_count,
            'overall_percentage': overall_pct,
            'threshold': threshold,
            'subject_breakdown': subject_breakdown,
            'defaulters': defaulters,
            'trend_labels': trend_labels,
            'trend_rates': trend_rates
        }
