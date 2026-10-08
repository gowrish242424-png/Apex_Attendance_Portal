"""Attendance Service Module.

Encapsulates all business logic, authorization verification, session creation,
record manipulation, analytical aggregations, and defaulter tracking for faculty.
"""

from datetime import date, datetime
import math
from sqlalchemy import func
from app.extensions import db
from app.models.academic import Class, Subject, FacultyAssignment
from app.models.user import StudentProfile, FacultyProfile
from app.models.attendance import AttendanceSession, AttendanceRecord
from app.models.settings import SystemSetting


class AttendanceService:
    """Service layer governing faculty attendance operations and calculations."""

    @staticmethod
    def get_faculty_assignments(faculty_id):
        """Retrieve all active course assignments for a faculty member."""
        return (
            FacultyAssignment.query
            .filter_by(faculty_id=faculty_id)
            .join(Class)
            .join(Subject)
            .order_by(Class.name.asc(), Subject.code.asc())
            .all()
        )

    @staticmethod
    def get_assigned_classes(faculty_id):
        """Retrieve distinct classes assigned to the given faculty."""
        assignments = FacultyAssignment.query.filter_by(faculty_id=faculty_id).all()
        class_ids = {a.class_id for a in assignments}
        if not class_ids:
            return []
        return Class.query.filter(Class.id.in_(class_ids)).order_by(Class.name.asc()).all()

    @staticmethod
    def get_assigned_subjects(faculty_id):
        """Retrieve distinct subjects assigned to the given faculty."""
        assignments = FacultyAssignment.query.filter_by(faculty_id=faculty_id).all()
        subject_ids = {a.subject_id for a in assignments}
        if not subject_ids:
            return []
        return Subject.query.filter(Subject.id.in_(subject_ids)).order_by(Subject.code.asc()).all()

    @staticmethod
    def verify_faculty_assignment(faculty_id, class_id, subject_id):
        """Verify that a faculty member is legitimately assigned to a class & subject.
        
        Returns the FacultyAssignment object if authorized, or None if forbidden.
        """
        try:
            class_id = int(class_id)
            subject_id = int(subject_id)
        except (ValueError, TypeError):
            return None

        return FacultyAssignment.query.filter_by(
            faculty_id=faculty_id,
            class_id=class_id,
            subject_id=subject_id
        ).first()

    @staticmethod
    def get_recent_sessions(faculty_id, limit=5):
        """Retrieve the most recent attendance sessions conducted by this faculty."""
        return (
            AttendanceSession.query
            .filter_by(faculty_id=faculty_id)
            .order_by(AttendanceSession.session_date.desc(), AttendanceSession.id.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_sessions_history(faculty_id, class_id=None, subject_id=None, date_from=None, date_to=None):
        """Retrieve historical attendance sessions for a faculty member with optional filters."""
        query = AttendanceSession.query.filter_by(faculty_id=faculty_id)

        if class_id:
            try:
                query = query.filter(AttendanceSession.class_id == int(class_id))
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

        return query.order_by(AttendanceSession.session_date.desc(), AttendanceSession.id.desc()).all()

    @staticmethod
    def get_enrolled_students(class_id):
        """Retrieve all active student profiles enrolled in a class ordered by roll number."""
        return (
            StudentProfile.query
            .filter_by(class_id=class_id)
            .order_by(StudentProfile.roll_number.asc())
            .all()
        )

    @staticmethod
    def find_session_by_slot(class_id, subject_id, session_date, session_slot):
        """Find an existing attendance session matching the exact class, subject, date, and slot."""
        return AttendanceSession.query.filter_by(
            class_id=class_id,
            subject_id=subject_id,
            session_date=session_date,
            session_slot=session_slot
        ).first()

    @staticmethod
    def create_attendance_session(faculty_id, class_id, subject_id, session_date, session_slot, attendance_records_data):
        """Create a new attendance session and atomic student records.
        
        Args:
            faculty_id (int): ID of the faculty profile.
            class_id (int): ID of the class.
            subject_id (int): ID of the subject.
            session_date (date): Date of the session.
            session_slot (str): Period or slot name (e.g. 'Period 1').
            attendance_records_data (list of dict): Each dict contains:
                'student_id': int,
                'status': 'PRESENT' | 'ABSENT',
                'remarks': str (optional)
                
        Returns:
            tuple: (session_obj, error_message)
        """
        # 1. Verify object-level assignment
        assignment = AttendanceService.verify_faculty_assignment(faculty_id, class_id, subject_id)
        if not assignment:
            return None, "Unauthorized: You are not assigned to instruct this class and subject combination."

        # 2. Check for duplicate session constraint
        existing = AttendanceService.find_session_by_slot(class_id, subject_id, session_date, session_slot)
        if existing:
            return None, "Attendance for this class, subject, date and period already exists."

        # 3. Verify enrolled students
        valid_students = {s.id for s in AttendanceService.get_enrolled_students(class_id)}

        try:
            session = AttendanceSession(
                class_id=class_id,
                subject_id=subject_id,
                faculty_id=faculty_id,
                session_date=session_date,
                session_slot=session_slot
            )
            db.session.add(session)
            db.session.flush()  # Generate session.id

            created_count = 0
            for record_data in attendance_records_data:
                sid = record_data.get('student_id')
                status = record_data.get('status', 'PRESENT').upper()
                remarks = record_data.get('remarks')

                # Ensure student belongs to class
                if sid not in valid_students:
                    continue

                if status not in ('PRESENT', 'ABSENT'):
                    status = 'PRESENT'

                rec = AttendanceRecord(
                    session_id=session.id,
                    student_id=sid,
                    status=status,
                    remarks=remarks
                )
                db.session.add(rec)
                created_count += 1

            db.session.commit()
            return session, None
        except Exception as e:
            db.session.rollback()
            return None, f"Database transaction failed: {str(e)}"

    @staticmethod
    def update_attendance_session(session, records_data):
        """Update student attendance records for an existing session atomically.
        
        Args:
            session (AttendanceSession): The session to update.
            records_data (list of dict): Each dict has 'student_id', 'status', 'remarks'
            
        Returns:
            tuple: (success_bool, message)
        """
        try:
            # Map existing records by student_id
            existing_records = {r.student_id: r for r in session.records}
            valid_students = {s.id for s in AttendanceService.get_enrolled_students(session.class_id)}

            updated_count = 0
            for record_data in records_data:
                sid = record_data.get('student_id')
                status = record_data.get('status', 'PRESENT').upper()
                remarks = record_data.get('remarks')

                if sid not in valid_students:
                    continue

                if status not in ('PRESENT', 'ABSENT'):
                    status = 'PRESENT'

                if sid in existing_records:
                    rec = existing_records[sid]
                    rec.status = status
                    if remarks is not None:
                        rec.remarks = remarks
                else:
                    # If record was missing for this student, insert it
                    rec = AttendanceRecord(
                        session_id=session.id,
                        student_id=sid,
                        status=status,
                        remarks=remarks
                    )
                    db.session.add(rec)
                updated_count += 1

            session.updated_at = datetime.now()
            db.session.commit()
            return True, f"Attendance updated successfully for {updated_count} students."
        except Exception as e:
            db.session.rollback()
            return False, f"Failed to update attendance: {str(e)}"

    @staticmethod
    def get_faculty_analytics(faculty_id):
        """Calculate complete attendance analytics and breakdown for a faculty member."""
        sessions = AttendanceSession.query.filter_by(faculty_id=faculty_id).all()
        session_ids = [s.id for s in sessions]

        total_sessions = len(sessions)
        total_records = 0
        present_count = 0
        absent_count = 0

        if session_ids:
            records = (
                AttendanceRecord.query
                .filter(AttendanceRecord.session_id.in_(session_ids))
                .all()
            )
            total_records = len(records)
            present_count = sum(1 for r in records if r.status == 'PRESENT')
            absent_count = sum(1 for r in records if r.status == 'ABSENT')

        overall_percentage = (
            round((present_count / total_records) * 100, 2)
            if total_records > 0 else 0.0
        )

        # Subject-wise analytics
        subject_breakdown = []
        assigned_subjects = AttendanceService.get_assigned_subjects(faculty_id)
        for sub in assigned_subjects:
            sub_sessions = [s for s in sessions if s.subject_id == sub.id]
            sub_session_ids = [s.id for s in sub_sessions]
            sub_total = 0
            sub_present = 0
            sub_absent = 0

            if sub_session_ids:
                sub_records = (
                    AttendanceRecord.query
                    .filter(AttendanceRecord.session_id.in_(sub_session_ids))
                    .all()
                )
                sub_total = len(sub_records)
                sub_present = sum(1 for r in sub_records if r.status == 'PRESENT')
                sub_absent = sub_total - sub_present

            sub_rate = round((sub_present / sub_total) * 100, 2) if sub_total > 0 else 0.0
            subject_breakdown.append({
                'subject': sub,
                'sessions_count': len(sub_sessions),
                'total_records': sub_total,
                'present_count': sub_present,
                'absent_count': sub_absent,
                'attendance_rate': sub_rate
            })

        # Class-wise analytics
        class_breakdown = []
        assigned_classes = AttendanceService.get_assigned_classes(faculty_id)
        for cls in assigned_classes:
            cls_sessions = [s for s in sessions if s.class_id == cls.id]
            cls_session_ids = [s.id for s in cls_sessions]
            cls_total = 0
            cls_present = 0
            cls_absent = 0

            if cls_session_ids:
                cls_records = (
                    AttendanceRecord.query
                    .filter(AttendanceRecord.session_id.in_(cls_session_ids))
                    .all()
                )
                cls_total = len(cls_records)
                cls_present = sum(1 for r in cls_records if r.status == 'PRESENT')
                cls_absent = cls_total - cls_present

            cls_rate = round((cls_present / cls_total) * 100, 2) if cls_total > 0 else 0.0
            class_breakdown.append({
                'class': cls,
                'sessions_count': len(cls_sessions),
                'total_records': cls_total,
                'present_count': cls_present,
                'absent_count': cls_absent,
                'attendance_rate': cls_rate
            })

        return {
            'total_sessions': total_sessions,
            'total_records': total_records,
            'present_count': present_count,
            'absent_count': absent_count,
            'overall_percentage': overall_percentage,
            'subject_breakdown': subject_breakdown,
            'class_breakdown': class_breakdown,
            'assigned_classes_count': len(assigned_classes),
            'assigned_subjects_count': len(assigned_subjects),
        }

    @staticmethod
    def get_faculty_defaulters(faculty_id, class_id=None, subject_id=None, custom_threshold=None):
        """Identify students below the institutional attendance threshold for assigned courses.
        
        Args:
            faculty_id (int): Faculty Profile ID.
            class_id (int, optional): Filter by class ID.
            subject_id (int, optional): Filter by subject ID.
            custom_threshold (float, optional): Custom cutoff percentage; if None, loads from SystemSetting.
            
        Returns:
            tuple: (defaulters_list, threshold_used)
        """
        if custom_threshold is not None:
            threshold = float(custom_threshold)
        else:
            threshold = float(SystemSetting.get_int('min_attendance_threshold', default=75))

        assignments = AttendanceService.get_faculty_assignments(faculty_id)

        if class_id:
            try:
                cid = int(class_id)
                assignments = [a for a in assignments if a.class_id == cid]
            except (ValueError, TypeError):
                pass

        if subject_id:
            try:
                sid = int(subject_id)
                assignments = [a for a in assignments if a.subject_id == sid]
            except (ValueError, TypeError):
                pass

        defaulters = []

        for assign in assignments:
            # Get all sessions conducted for this class and subject by this faculty
            sessions = (
                AttendanceSession.query
                .filter_by(
                    class_id=assign.class_id,
                    subject_id=assign.subject_id,
                    faculty_id=faculty_id
                )
                .all()
            )
            session_ids = [s.id for s in sessions]
            total_sessions = len(sessions)

            if total_sessions == 0:
                continue

            # Query all enrolled students in this class
            enrolled_students = AttendanceService.get_enrolled_students(assign.class_id)

            for student in enrolled_students:
                # Query attendance records for this student across these sessions
                records = (
                    AttendanceRecord.query
                    .filter(
                        AttendanceRecord.session_id.in_(session_ids),
                        AttendanceRecord.student_id == student.id
                    )
                    .all()
                )
                total_recorded = len(records)
                if total_recorded == 0:
                    continue

                attended = sum(1 for r in records if r.status == 'PRESENT')
                percentage = round((attended / total_recorded) * 100, 2)

                if percentage < threshold:
                    defaulters.append({
                        'student': student,
                        'class': assign.class_group,
                        'subject': assign.subject,
                        'attended': attended,
                        'total': total_recorded,
                        'percentage': percentage,
                        'shortage': round(threshold - percentage, 2)
                    })

        # Sort defaulters by attendance percentage ascending (most severe first)
        defaulters.sort(key=lambda d: d['percentage'])
        return defaulters, threshold

    # =========================================================================
    # Student Portal Service Methods
    # =========================================================================

    @staticmethod
    def get_student_applicable_subjects(student_profile):
        """Retrieve all subjects associated with the student's cohort/curriculum."""
        if not student_profile or not student_profile.class_id:
            return []

        # 1. Subjects assigned to the student's class
        assigned_ids = {
            a.subject_id for a in FacultyAssignment.query.filter_by(class_id=student_profile.class_id).all()
        }
        # 2. Subjects with recorded attendance sessions for this class
        session_ids = {
            s.subject_id for s in AttendanceSession.query.filter_by(class_id=student_profile.class_id).all()
        }
        # 3. Department and semester curriculum subjects
        curriculum_ids = {
            s.id for s in Subject.query.filter_by(
                department_id=student_profile.department_id,
                semester=student_profile.semester
            ).all()
        }
        all_ids = assigned_ids | session_ids | curriculum_ids
        if not all_ids:
            return []
        return Subject.query.filter(Subject.id.in_(all_ids)).order_by(Subject.code.asc()).all()

    @staticmethod
    def get_student_overall_summary(student_profile):
        """Calculate overall attendance statistics across all subjects for a student."""
        threshold = float(SystemSetting.get_int('min_attendance_threshold', default=75))
        if not student_profile:
            return {
                'total': 0,
                'attended': 0,
                'absent': 0,
                'percentage': 0.0,
                'threshold': threshold,
                'status': 'Not Started',
                'is_eligible': False
            }

        records = AttendanceRecord.query.filter_by(student_id=student_profile.id).all()
        total = len(records)
        if total == 0:
            return {
                'total': 0,
                'attended': 0,
                'absent': 0,
                'percentage': 0.0,
                'threshold': threshold,
                'status': 'Not Started',
                'is_eligible': False
            }

        attended = sum(1 for r in records if r.status == 'PRESENT')
        absent = total - attended
        percentage = round((attended / total) * 100, 2)
        is_eligible = percentage >= threshold

        return {
            'total': total,
            'attended': attended,
            'absent': absent,
            'percentage': percentage,
            'threshold': threshold,
            'status': 'Eligible' if is_eligible else 'Shortage',
            'is_eligible': is_eligible
        }

    @staticmethod
    def get_student_subject_summaries(student_profile):
        """Calculate per-subject attendance summaries for all applicable subjects."""
        threshold = float(SystemSetting.get_int('min_attendance_threshold', default=75))
        applicable_subjects = AttendanceService.get_student_applicable_subjects(student_profile)
        summaries = []
        shortage_count = 0
        safe_count = 0

        for sub in applicable_subjects:
            records = (
                AttendanceRecord.query
                .join(AttendanceSession)
                .filter(
                    AttendanceRecord.student_id == student_profile.id,
                    AttendanceSession.subject_id == sub.id
                )
                .all()
            )
            total = len(records)
            if total == 0:
                summaries.append({
                    'subject': sub,
                    'total': 0,
                    'attended': 0,
                    'absent': 0,
                    'percentage': None,
                    'status': 'Not Started',
                    'is_shortage': False,
                    'shortage': 0.0,
                    'threshold': threshold
                })
            else:
                attended = sum(1 for r in records if r.status == 'PRESENT')
                absent = total - attended
                pct = round((attended / total) * 100, 2)
                is_shortage = pct < threshold
                shortage_val = round(threshold - pct, 2) if is_shortage else 0.0
                if is_shortage:
                    shortage_count += 1
                else:
                    safe_count += 1

                summaries.append({
                    'subject': sub,
                    'total': total,
                    'attended': attended,
                    'absent': absent,
                    'percentage': pct,
                    'status': 'Shortage' if is_shortage else 'Good',
                    'is_shortage': is_shortage,
                    'shortage': shortage_val,
                    'threshold': threshold
                })

        return {
            'subjects': summaries,
            'total_subjects': len(summaries),
            'shortage_count': shortage_count,
            'safe_count': safe_count,
            'threshold': threshold
        }

    @staticmethod
    def get_student_subject_details(student_profile, subject_id):
        """Retrieve detailed session-by-session records for an individual subject."""
        try:
            sid = int(subject_id)
        except (ValueError, TypeError):
            return None

        # Verify subject is applicable
        applicable_subjects = {s.id: s for s in AttendanceService.get_student_applicable_subjects(student_profile)}
        if sid not in applicable_subjects:
            return None

        subject = applicable_subjects[sid]
        threshold = float(SystemSetting.get_int('min_attendance_threshold', default=75))

        records = (
            AttendanceRecord.query
            .join(AttendanceSession)
            .filter(
                AttendanceRecord.student_id == student_profile.id,
                AttendanceSession.subject_id == sid
            )
            .order_by(AttendanceSession.session_date.desc(), AttendanceSession.id.desc())
            .all()
        )

        total = len(records)
        attended = sum(1 for r in records if r.status == 'PRESENT')
        absent = total - attended
        percentage = round((attended / total) * 100, 2) if total > 0 else None
        is_shortage = percentage is not None and percentage < threshold
        shortage = round(threshold - percentage, 2) if is_shortage else 0.0
        status = 'Shortage' if is_shortage else ('Good' if percentage is not None else 'Not Started')

        return {
            'subject': subject,
            'records': records,
            'total': total,
            'attended': attended,
            'absent': absent,
            'percentage': percentage,
            'threshold': threshold,
            'is_shortage': is_shortage,
            'shortage': shortage,
            'status': status
        }

    @staticmethod
    def get_student_attendance_history(student_profile, subject_id=None, date_from=None, date_to=None, status=None):
        """Retrieve chronological attendance history for a student with server-side filters."""
        query = (
            AttendanceRecord.query
            .join(AttendanceSession)
            .filter(AttendanceRecord.student_id == student_profile.id)
        )

        if subject_id:
            try:
                sid = int(subject_id)
                query = query.filter(AttendanceSession.subject_id == sid)
            except (ValueError, TypeError):
                pass

        if status and status.upper() in ('PRESENT', 'ABSENT'):
            query = query.filter(AttendanceRecord.status == status.upper())

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

        return query.order_by(AttendanceSession.session_date.desc(), AttendanceSession.id.desc()).all()

    @staticmethod
    def calculate_what_if_attendance(student_profile, subject_id, upcoming_classes, custom_threshold=None):
        """Simulate future attendance trajectory without modifying database."""
        try:
            sid = int(subject_id)
            upcoming = int(upcoming_classes)
        except (ValueError, TypeError):
            return None, "Invalid subject ID or number of classes."

        if upcoming < 0:
            return None, "Upcoming classes cannot be negative."

        if upcoming > 500:
            return None, "Upcoming classes cannot exceed 500."

        # Verify subject applicability
        details = AttendanceService.get_student_subject_details(student_profile, sid)
        if not details:
            return None, "Subject is not part of your curriculum."

        threshold = custom_threshold if custom_threshold is not None else details['threshold']
        present = details['attended']
        total = details['total']
        current_pct = details['percentage'] if details['percentage'] is not None else 0.0

        new_total = total + upcoming
        attend_all_present = present + upcoming
        attend_all_pct = round((attend_all_present / new_total) * 100, 2) if new_total > 0 else 0.0

        miss_all_present = present
        miss_all_pct = round((miss_all_present / new_total) * 100, 2) if new_total > 0 else 0.0

        # Minimum needed out of upcoming classes:
        # (present + x) / new_total >= threshold / 100
        target_present = math.ceil((threshold * new_total) / 100.0)
        needed_from_upcoming = max(0, target_present - present)

        is_possible = needed_from_upcoming <= upcoming

        # Continuous classes needed from now (unconstrained upcoming):
        continuous_needed = 0
        if current_pct < threshold and threshold < 100:
            numerator = (threshold * total) - (100 * present)
            denominator = 100 - threshold
            continuous_needed = max(1, math.ceil(numerator / denominator))

        explanation = ""
        if upcoming == 0:
            explanation = f"Your current attendance in {details['subject'].name} is {current_pct}%."
        elif not is_possible:
            explanation = (
                f"Even if you attend all {upcoming} upcoming classes, your attendance will reach "
                f"{attend_all_pct}%, which is still below the {threshold}% required threshold."
            )
        elif needed_from_upcoming == 0:
            explanation = (
                f"You are safely above the threshold. Even if you miss all {upcoming} upcoming classes, "
                f"your attendance will be {miss_all_pct}% (>= {threshold}%)."
            )
        else:
            explanation = (
                f"You must attend at least {needed_from_upcoming} out of the next {upcoming} classes "
                f"to achieve or maintain the {threshold}% threshold."
            )

        return {
            'subject': details['subject'],
            'threshold': threshold,
            'current_present': present,
            'current_total': total,
            'current_percentage': current_pct,
            'upcoming_classes': upcoming,
            'new_total': new_total,
            'attend_all_present': attend_all_present,
            'attend_all_percentage': attend_all_pct,
            'miss_all_present': miss_all_present,
            'miss_all_percentage': miss_all_pct,
            'needed_from_upcoming': needed_from_upcoming,
            'is_possible': is_possible,
            'continuous_needed': continuous_needed,
            'explanation': explanation
        }, None
