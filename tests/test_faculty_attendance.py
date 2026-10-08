"""Automated Test Suite for Phase 5: Faculty Attendance Engine.

Covers:
- Faculty dashboard rendering & role checks
- Course allocation filtering & strict object-level authorization
- Attendance session creation & duplicate prevention
- Attendance records (PRESENT / ABSENT) & database constraints
- Attendance session editing & ownership enforcement
- History browsing & cross-faculty data isolation
- Attendance analytics & safe division handling (zero-record edge cases)
- Defaulters tracking based on SystemSetting threshold
- Security & tamper prevention (URL/POST manipulation)
"""

import unittest
from datetime import date, timedelta
from app import create_app
from app.extensions import db
from app.models.user import User, FacultyProfile, StudentProfile
from app.models.academic import Department, Class, Subject, FacultyAssignment
from app.models.attendance import AttendanceSession, AttendanceRecord
from app.models.settings import SystemSetting
from app.utils.seed_data import seed_database
from app.services.attendance_service import AttendanceService


class Phase5FacultyAttendanceTestCase(unittest.TestCase):
    def setUp(self):
        """Set up in-memory SQLite database and test client."""
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Seed realistic base data
        seed_database(verbose=False)

        # Retrieve test entities
        self.fac_sharma_user = User.query.filter_by(username='fac_sharma').first()
        self.fac_sharma_prof = self.fac_sharma_user.faculty_profile

        self.fac_verma_user = User.query.filter_by(username='fac_verma').first()
        self.fac_verma_prof = self.fac_verma_user.faculty_profile

        self.class_cse = Class.query.filter_by(name='CSE-3A').first()
        self.class_ece = Class.query.filter_by(name='ECE-3A').first()

        self.sub_cs501 = Subject.query.filter_by(code='CS501').first()
        self.sub_ec501 = Subject.query.filter_by(code='EC501').first()

    def tearDown(self):
        """Clean up in-memory database."""
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def login_faculty_sharma(self):
        """Helper to log in as Dr. Rajesh Sharma (teaches CSE-3A: CS501, CS503)."""
        return self.client.post('/login', data={'username': 'fac_sharma', 'password': 'faculty123'})

    def login_faculty_verma(self):
        """Helper to log in as Dr. Amit Verma (teaches ECE-3A: EC501, EC502)."""
        return self.client.post('/login', data={'username': 'fac_verma', 'password': 'faculty123'})

    def login_student(self):
        """Helper to log in as Aarav Patel (student in CSE-3A)."""
        return self.client.post('/login', data={'username': 'student_aarav', 'password': 'student123'})

    # =========================================================================
    # A. Faculty Dashboard
    # =========================================================================

    def test_faculty_dashboard_access(self):
        """Verify faculty can access dashboard and view own profile and allocations."""
        self.login_faculty_sharma()
        res = self.client.get('/faculty/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Dr. Rajesh Sharma', res.data)
        self.assertIn(b'Faculty Role', res.data)
        self.assertIn(b'CS501', res.data)
        self.assertIn(b'CS503', res.data)
        self.assertIn(b'Mark Attendance', res.data)
        self.assertIn(b'Attendance History', res.data)
        self.assertIn(b'Analytics', res.data)
        self.assertIn(b'Defaulters', res.data)

    def test_student_cannot_access_faculty_dashboard(self):
        """Verify Student attempting to access /faculty/dashboard receives HTTP 403 Forbidden."""
        self.login_student()
        res = self.client.get('/faculty/dashboard')
        self.assertEqual(res.status_code, 403)
        self.assertIn(b'403 Forbidden', res.data)

    def test_unauthenticated_redirected_from_faculty_dashboard(self):
        """Verify unauthenticated user is redirected to login page."""
        res = self.client.get('/faculty/dashboard')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers['Location'])

    def test_faculty_dashboard_data_isolation(self):
        """Verify faculty cannot see allocations belonging to other faculty members."""
        self.login_faculty_sharma()
        res = self.client.get('/faculty/dashboard')
        self.assertEqual(res.status_code, 200)
        # Sharma should NOT see Verma's ECE subjects on their dashboard
        self.assertNotIn(b'EC501', res.data)
        self.assertNotIn(b'Microprocessors & Microcontrollers', res.data)

    # =========================================================================
    # B. Assignment Filtering & Object-Level Access Control
    # =========================================================================

    def test_mark_page_renders_only_own_allocations(self):
        """Verify Mark Attendance dropdown contains only current faculty's assigned courses."""
        self.login_faculty_sharma()
        res = self.client.get('/faculty/attendance/mark')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'CS501', res.data)
        self.assertIn(b'CS503', res.data)
        self.assertNotIn(b'EC501', res.data)
        self.assertNotIn(b'EC502', res.data)

    def test_mark_page_rejects_unassigned_combo_get(self):
        """Verify GET /faculty/attendance/mark with unassigned class/subject returns HTTP 403."""
        self.login_faculty_sharma()
        # Sharma is NOT assigned to ECE-3A (class_ece.id) and EC501 (sub_ec501.id)
        res = self.client.get(f'/faculty/attendance/mark?class_id={self.class_ece.id}&subject_id={self.sub_ec501.id}')
        self.assertEqual(res.status_code, 403)

    def test_mark_page_rejects_unassigned_combo_post(self):
        """Verify POST /faculty/attendance/mark with unassigned class/subject returns HTTP 403."""
        self.login_faculty_sharma()
        res = self.client.post('/faculty/attendance/mark', data={
            'class_id': self.class_ece.id,
            'subject_id': self.sub_ec501.id,
            'session_date': date.today().isoformat(),
            'session_slot': 'Period 1'
        })
        self.assertEqual(res.status_code, 403)

    # =========================================================================
    # C. Attendance Session Creation & Validation
    # =========================================================================

    def test_create_valid_attendance_session(self):
        """Verify valid attendance submission creates session and records correctly."""
        self.login_faculty_sharma()
        test_date = (date.today() + timedelta(days=1)).isoformat()
        slot = 'Period 8'

        # Get enrolled students in CSE-3A
        students = StudentProfile.query.filter_by(class_id=self.class_cse.id).all()
        post_data = {
            'class_id': self.class_cse.id,
            'subject_id': self.sub_cs501.id,
            'session_date': test_date,
            'session_slot': slot
        }
        for s in students:
            post_data[f'status_{s.id}'] = 'PRESENT'
            post_data[f'remarks_{s.id}'] = 'Regular'

        res = self.client.post('/faculty/attendance/mark', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Attendance saved successfully', res.data)

        # Verify database session created
        session = AttendanceSession.query.filter_by(
            class_id=self.class_cse.id,
            subject_id=self.sub_cs501.id,
            session_slot=slot
        ).first()
        self.assertIsNotNone(session)
        self.assertEqual(session.faculty_id, self.fac_sharma_prof.id)
        self.assertEqual(len(session.records), len(students))
        self.assertEqual(session.present_count, len(students))
        self.assertEqual(session.absent_count, 0)

    def test_duplicate_session_prevention(self):
        """Verify attempting to record attendance for an existing slot redirects with warning."""
        self.login_faculty_sharma()
        # Find an existing session for Sharma
        existing = AttendanceSession.query.filter_by(
            class_id=self.class_cse.id,
            subject_id=self.sub_cs501.id,
            faculty_id=self.fac_sharma_prof.id
        ).first()
        self.assertIsNotNone(existing)

        # Attempt to create duplicate session on same date & slot
        post_data = {
            'class_id': existing.class_id,
            'subject_id': existing.subject_id,
            'session_date': existing.session_date.isoformat(),
            'session_slot': existing.session_slot
        }
        res = self.client.post('/faculty/attendance/mark', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Attendance for this class, subject, date and period already exists', res.data)

    def test_missing_fields_rejected(self):
        """Verify submitting without required fields fails gracefully."""
        self.login_faculty_sharma()
        res = self.client.post('/faculty/attendance/mark', data={
            'class_id': '',
            'subject_id': '',
            'session_date': ''
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Please specify class, subject, and session date', res.data)

    # =========================================================================
    # D. Attendance Records & Database Constraints
    # =========================================================================

    def test_attendance_records_present_and_absent(self):
        """Verify records correctly store both PRESENT and ABSENT marks."""
        self.login_faculty_sharma()
        test_date = (date.today() + timedelta(days=2)).isoformat()
        slot = 'Period 7'

        students = StudentProfile.query.filter_by(class_id=self.class_cse.id).order_by(StudentProfile.id).all()
        self.assertGreaterEqual(len(students), 2)

        # Mark first student PRESENT, second ABSENT
        post_data = {
            'class_id': self.class_cse.id,
            'subject_id': self.sub_cs501.id,
            'session_date': test_date,
            'session_slot': slot,
            f'status_{students[0].id}': 'PRESENT',
            f'status_{students[1].id}': 'ABSENT',
            f'remarks_{students[1].id}': 'Medical'
        }
        # Default rest to PRESENT
        for s in students[2:]:
            post_data[f'status_{s.id}'] = 'PRESENT'

        res = self.client.post('/faculty/attendance/mark', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        session = AttendanceSession.query.filter_by(
            class_id=self.class_cse.id,
            subject_id=self.sub_cs501.id,
            session_slot=slot
        ).first()
        self.assertIsNotNone(session)

        rec0 = AttendanceRecord.query.filter_by(session_id=session.id, student_id=students[0].id).first()
        rec1 = AttendanceRecord.query.filter_by(session_id=session.id, student_id=students[1].id).first()
        self.assertEqual(rec0.status, 'PRESENT')
        self.assertEqual(rec1.status, 'ABSENT')
        self.assertEqual(rec1.remarks, 'Medical')

    def test_duplicate_student_record_database_constraint(self):
        """Verify database UniqueConstraint('session_id', 'student_id') prevents duplicate records."""
        existing = AttendanceSession.query.first()
        student = StudentProfile.query.filter_by(class_id=existing.class_id).first()

        # Try to insert a second record for the same student in the same session
        duplicate_rec = AttendanceRecord(
            session_id=existing.id,
            student_id=student.id,
            status='PRESENT'
        )
        db.session.add(duplicate_rec)
        with self.assertRaises(Exception):
            db.session.commit()
        db.session.rollback()

    # =========================================================================
    # E. Attendance Editing & Ownership Enforcement
    # =========================================================================

    def test_authorized_faculty_can_edit_own_session(self):
        """Verify faculty can edit student records in their own session."""
        self.login_faculty_sharma()
        session = AttendanceSession.query.filter_by(faculty_id=self.fac_sharma_prof.id).first()
        self.assertIsNotNone(session)

        # GET edit page
        res = self.client.get(f'/faculty/attendance/{session.id}/edit')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Modify Attendance Session', res.data)

        # Target first record: toggle its status
        first_rec = session.records[0]
        new_status = 'ABSENT' if first_rec.status == 'PRESENT' else 'PRESENT'

        post_data = {}
        for r in session.records:
            if r.id == first_rec.id:
                post_data[f'status_{r.student_id}'] = new_status
                post_data[f'remarks_{r.student_id}'] = 'Updated by faculty'
            else:
                post_data[f'status_{r.student_id}'] = r.status

        post_res = self.client.post(f'/faculty/attendance/{session.id}/edit', data=post_data, follow_redirects=True)
        self.assertEqual(post_res.status_code, 200)
        self.assertIn(b'Attendance updated successfully', post_res.data)

        # Verify DB updated
        db.session.refresh(first_rec)
        self.assertEqual(first_rec.status, new_status)
        self.assertEqual(first_rec.remarks, 'Updated by faculty')

    def test_unauthorized_faculty_blocked_from_editing_other_session(self):
        """Verify faculty receives HTTP 403 when attempting to edit another faculty's session."""
        self.login_faculty_sharma()
        # Find a session belonging to Verma
        verma_session = AttendanceSession.query.filter_by(faculty_id=self.fac_verma_prof.id).first()
        self.assertIsNotNone(verma_session)

        # Sharma tries to GET Verma's session edit page
        res = self.client.get(f'/faculty/attendance/{verma_session.id}/edit')
        self.assertEqual(res.status_code, 403)

        # Sharma tries to POST an edit to Verma's session
        post_res = self.client.post(f'/faculty/attendance/{verma_session.id}/edit', data={
            f'status_{verma_session.records[0].student_id}': 'ABSENT'
        })
        self.assertEqual(post_res.status_code, 403)

    def test_student_blocked_from_editing_session(self):
        """Verify Student receives HTTP 403 when attempting to access session edit route."""
        self.login_student()
        session = AttendanceSession.query.first()
        res = self.client.get(f'/faculty/attendance/{session.id}/edit')
        self.assertEqual(res.status_code, 403)

    def test_nonexistent_session_edit_returns_404(self):
        """Verify editing nonexistent session returns HTTP 404."""
        self.login_faculty_sharma()
        res = self.client.get('/faculty/attendance/99999/edit')
        self.assertEqual(res.status_code, 404)

    # =========================================================================
    # F. Attendance History
    # =========================================================================

    def test_history_shows_only_own_sessions(self):
        """Verify history shows only sessions conducted by the logged-in faculty."""
        self.login_faculty_sharma()
        res = self.client.get('/faculty/attendance/history')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Attendance History', res.data)
        self.assertIn(b'CS501', res.data)
        # Should not show Verma's ECE sessions
        self.assertNotIn(b'EC501', res.data)

    def test_history_filtering_by_class_and_subject(self):
        """Verify history filters work accurately."""
        self.login_faculty_sharma()
        res = self.client.get(f'/faculty/attendance/history?class_id={self.class_cse.id}&subject_id={self.sub_cs501.id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'CS501', res.data)

    def test_student_blocked_from_history(self):
        """Verify student is forbidden from accessing history route."""
        self.login_student()
        res = self.client.get('/faculty/attendance/history')
        self.assertEqual(res.status_code, 403)

    # =========================================================================
    # G. Attendance Analytics
    # =========================================================================

    def test_analytics_calculation(self):
        """Verify analytics calculates rates, totals, and subject breakdown accurately."""
        self.login_faculty_sharma()
        res = self.client.get('/faculty/attendance/analytics')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Faculty Attendance Analytics', res.data)
        self.assertIn(b'Total Sessions', res.data)
        self.assertIn(b'CS501', res.data)
        self.assertIn(b'CS503', res.data)

    def test_analytics_zero_records_safe(self):
        """Verify analytics does not crash with ZeroDivisionError when a faculty has zero sessions."""
        # Create a new faculty member with an assignment but 0 recorded sessions
        new_user = User(username='fac_new', email='new@apex.edu', role='faculty', is_active=True)
        new_user.set_password('faculty123')
        db.session.add(new_user)
        db.session.flush()

        new_prof = FacultyProfile(
            user_id=new_user.id,
            employee_id='EMP-NEW-999',
            full_name='Prof. Newbie',
            department_id=self.class_cse.department_id,
            designation='Lecturer'
        )
        db.session.add(new_prof)
        db.session.flush()

        new_assign = FacultyAssignment(
            faculty_id=new_prof.id,
            class_id=self.class_cse.id,
            subject_id=self.sub_cs501.id,
            academic_year='2026-2027'
        )
        db.session.add(new_assign)
        db.session.commit()

        # Compute service analytics directly
        analytics = AttendanceService.get_faculty_analytics(new_prof.id)
        self.assertEqual(analytics['total_sessions'], 0)
        self.assertEqual(analytics['total_records'], 0)
        self.assertEqual(analytics['overall_percentage'], 0.0)

        # Log in as fac_new and verify template renders cleanly
        self.client.post('/login', data={'username': 'fac_new', 'password': 'faculty123'})
        res = self.client.get('/faculty/attendance/analytics')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'0.0%', res.data)

    # =========================================================================
    # H. Defaulters Tracking
    # =========================================================================

    def test_defaulters_identified_correctly(self):
        """Verify students below 75% are identified as defaulters for faculty's courses."""
        self.login_faculty_sharma()
        res = self.client.get('/faculty/attendance/defaulters')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Attendance Defaulters Tracking', res.data)
        # Vikram Singh and Kabir Mehta were seeded with ~50-60% attendance in CSE-3A
        self.assertIn(b'Vikram Singh', res.data)
        self.assertIn(b'2026CSE005', res.data)

    def test_defaulters_threshold_from_system_settings(self):
        """Verify defaulters calculation uses SystemSetting threshold."""
        threshold = SystemSetting.get_int('min_attendance_threshold', default=75)
        self.assertEqual(threshold, 75)

        # Sharma's defaulters at 75%
        defaulters_75, t_val = AttendanceService.get_faculty_defaulters(self.fac_sharma_prof.id)
        self.assertEqual(t_val, 75.0)
        self.assertGreaterEqual(len(defaulters_75), 1)

        # If threshold is lowered to 10%, no students should be defaulters
        defaulters_10, _ = AttendanceService.get_faculty_defaulters(self.fac_sharma_prof.id, custom_threshold=10.0)
        self.assertEqual(len(defaulters_10), 0)

    def test_defaulters_data_isolation(self):
        """Verify faculty cannot see defaulters from other faculty's classes."""
        self.login_faculty_sharma()
        res = self.client.get('/faculty/attendance/defaulters')
        self.assertEqual(res.status_code, 200)
        # Rahul Ghosh is a defaulter in ECE-3A taught by Verma
        self.assertNotIn(b'Rahul Ghosh', res.data)
        self.assertNotIn(b'2026ECE005', res.data)

    # =========================================================================
    # I. Security & Tamper Resistance
    # =========================================================================

    def test_unauthenticated_requests_redirected(self):
        """Verify unauthenticated access to all faculty routes redirects to login."""
        protected_routes = [
            '/faculty/dashboard',
            '/faculty/attendance/mark',
            '/faculty/attendance/history',
            '/faculty/attendance/analytics',
            '/faculty/attendance/defaulters',
            '/faculty/attendance/1/edit',
        ]
        for path in protected_routes:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 302, f"Failed for {path}")
            self.assertIn('/login', res.headers['Location'])

    def test_student_role_forbidden_on_all_faculty_routes(self):
        """Verify student receives HTTP 403 on all faculty routes."""
        self.login_student()
        protected_routes = [
            '/faculty/dashboard',
            '/faculty/attendance/mark',
            '/faculty/attendance/history',
            '/faculty/attendance/analytics',
            '/faculty/attendance/defaulters',
            '/faculty/attendance/1/edit',
        ]
        for path in protected_routes:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 403, f"Failed for {path}")


if __name__ == '__main__':
    unittest.main()
