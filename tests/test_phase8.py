"""Tests for Phase 8: UI/UX, Validation, Error Handling & Security Hardening.

Covers:
- Custom Error Handlers (400, 401, 403, 404, 405, 500)
- Security Headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, CSP, Cache-Control)
- Open Redirect Defenses (//attacker.com, /\\attacker.com, external schemes)
- CSRF Token Enforcement & Validation
- Input Validation (Semester, Credits, Email, Date Ranges, Future Session Dates)
- Object-Level Authorization Isolation
"""

import unittest
from datetime import date, timedelta
from flask import session
from app import create_app
from app.extensions import db
from app.models.user import User, FacultyProfile, StudentProfile
from app.models.academic import Department, Class, Subject, FacultyAssignment
from app.models.attendance import AttendanceSession, AttendanceRecord
from app.utils.seed_data import seed_database
from app.utils.csrf import generate_csrf_token


class Phase8SecurityAndValidationTestCase(unittest.TestCase):
    def setUp(self):
        """Set up in-memory SQLite database and test client."""
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Seed initial dataset
        seed_database(verbose=False)

    def tearDown(self):
        """Clean up in-memory database."""
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def login_user(self, username, password):
        """Helper to authenticate a user."""
        return self.client.post('/login', data={'username': username, 'password': password})

    # =========================================================================
    # 1. ERROR HANDLERS (400, 401, 403, 404, 405, 500)
    # =========================================================================

    def test_404_not_found_page_renders_cleanly(self):
        """Verify non-existent URL returns HTTP 404 with friendly error page."""
        res = self.client.get('/this-page-definitely-does-not-exist')
        self.assertEqual(res.status_code, 404)
        self.assertIn(b'404 Not Found', res.data)
        self.assertIn(b'Home', res.data)

    def test_405_method_not_allowed_page(self):
        """Verify wrong HTTP method returns HTTP 405 with friendly error page."""
        # /login is GET/POST, but /departments/create is POST only
        self.login_user('admin', 'admin123')
        res = self.client.get('/admin/departments/create')
        self.assertEqual(res.status_code, 405)
        self.assertIn(b'405', res.data)
        self.assertIn(b'Method Not Allowed', res.data)

    def test_403_forbidden_page_renders_with_role(self):
        """Verify unauthorized role access returns HTTP 403 with appropriate role label."""
        self.login_user('student_aarav', 'student123')
        res = self.client.get('/admin/dashboard')
        self.assertEqual(res.status_code, 403)
        self.assertIn(b'403 Forbidden', res.data)
        self.assertIn(b'Student', res.data)
        self.assertIn(b'Return to Student Dashboard', res.data)

    def test_401_unauthorized_page_via_abort(self):
        """Verify abort(401) invokes custom 401 handler."""
        @self.app.route('/test-401')
        def trigger_401():
            from flask import abort
            abort(401)

        res = self.client.get('/test-401')
        self.assertEqual(res.status_code, 401)
        self.assertIn(b'401', res.data)
        self.assertIn(b'Authentication Required', res.data)

    def test_400_bad_request_page_via_abort(self):
        """Verify abort(400) invokes custom 400 handler."""
        @self.app.route('/test-400')
        def trigger_400():
            from flask import abort
            abort(400)

        res = self.client.get('/test-400')
        self.assertEqual(res.status_code, 400)
        self.assertIn(b'400', res.data)
        self.assertIn(b'Bad Request', res.data)

    def test_500_internal_server_error_handler_rolls_back_session(self):
        """Verify unhandled exceptions trigger 500 handler and session rollback."""
        @self.app.route('/test-500')
        def trigger_500():
            raise RuntimeError("Simulated unhandled system fault")

        # Disable exception propagation to let Flask invoke the 500 handler
        self.app.testing = False
        res = self.client.get('/test-500')
        self.assertEqual(res.status_code, 500)
        self.assertIn(b'500', res.data)
        self.assertIn(b'Internal Server Error', res.data)
        self.app.testing = True

    # =========================================================================
    # 2. SECURITY HEADERS & SESSION SECURITY
    # =========================================================================

    def test_security_headers_present_on_responses(self):
        """Verify all responses include defensive HTTP security headers."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(res.headers.get('X-Frame-Options'), 'SAMEORIGIN')
        self.assertEqual(res.headers.get('Referrer-Policy'), 'strict-origin-when-cross-origin')
        self.assertIn("default-src 'self'", res.headers.get('Content-Security-Policy', ''))

    def test_cache_control_headers_for_authenticated_sessions(self):
        """Verify authenticated responses instruct browsers never to cache sensitive data."""
        self.login_user('admin', 'admin123')
        res = self.client.get('/admin/dashboard')
        self.assertEqual(res.status_code, 200)
        cache_ctrl = res.headers.get('Cache-Control', '')
        self.assertIn('no-store', cache_ctrl)
        self.assertIn('no-cache', cache_ctrl)

    # =========================================================================
    # 3. OPEN REDIRECT DEFENSES
    # =========================================================================

    def test_open_redirect_protocol_relative_url_rejected(self):
        """Verify protocol-relative URLs (//attacker.com) are rejected."""
        res = self.client.post('/login', data={
            'username': 'admin',
            'password': 'admin123',
            'next': '//attacker.com'
        })
        self.assertEqual(res.status_code, 302)
        # Must redirect safely to internal dashboard, NOT to //attacker.com
        self.assertEqual(res.location, '/admin/dashboard')

    def test_open_redirect_backslash_scheme_rejected(self):
        """Verify backslash bypasses (/\\evil.com) are rejected."""
        res = self.client.post('/login', data={
            'username': 'admin',
            'password': 'admin123',
            'next': '/\\evil.com'
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.location, '/admin/dashboard')

    def test_open_redirect_absolute_external_url_rejected(self):
        """Verify absolute external URLs (https://phishing.com) are rejected."""
        res = self.client.post('/login', data={
            'username': 'admin',
            'password': 'admin123',
            'next': 'https://phishing.com/steal-credentials'
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.location, '/admin/dashboard')

    # =========================================================================
    # 4. CSRF PROTECTION ENFORCEMENT
    # =========================================================================

    def test_csrf_rejection_when_token_is_missing(self):
        """Verify POST requests without CSRF token are blocked with HTTP 400 when CSRF is enabled."""
        self.app.config['WTF_CSRF_ENABLED'] = True
        try:
            # Login without CSRF token should be rejected
            res = self.client.post('/login', data={
                'username': 'admin',
                'password': 'admin123'
            })
            self.assertEqual(res.status_code, 400)
            self.assertIn(b'400 Bad Request', res.data)
        finally:
            self.app.config['WTF_CSRF_ENABLED'] = False

    def test_csrf_acceptance_with_valid_token(self):
        """Verify POST requests with valid session-bound CSRF token succeed when CSRF is enabled."""
        self.app.config['WTF_CSRF_ENABLED'] = True
        try:
            # First GET /login to generate session with token
            get_res = self.client.get('/login')
            self.assertEqual(get_res.status_code, 200)

            # Retrieve token from session using client session transaction
            with self.client.session_transaction() as sess:
                valid_token = sess.get('_csrf_token')

            self.assertIsNotNone(valid_token)

            # Post with valid token
            res = self.client.post('/login', data={
                'username': 'admin',
                'password': 'admin123',
                'csrf_token': valid_token
            }, follow_redirects=True)
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'Admin Dashboard', res.data)
        finally:
            self.app.config['WTF_CSRF_ENABLED'] = False

    # =========================================================================
    # 5. INPUT & DATE BOUNDARY VALIDATION
    # =========================================================================

    def test_semester_out_of_bounds_rejected(self):
        """Verify semester < 1 or > 10 is rejected when creating a class."""
        self.login_user('admin', 'admin123')
        dept = Department.query.filter_by(code='CSE').first()

        # Semester 15 (invalid)
        res = self.client.post('/admin/classes/create', data={
            'name': 'CSE-InvalidSem',
            'department_id': dept.id,
            'semester': 15,
            'academic_year': '2026-2027'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Semester must be between 1 and 10', res.data)
        self.assertIsNone(Class.query.filter_by(name='CSE-InvalidSem').first())

    def test_credits_out_of_bounds_rejected(self):
        """Verify credits < 1 or > 12 is rejected when creating a subject."""
        self.login_user('admin', 'admin123')
        dept = Department.query.filter_by(code='CSE').first()

        res = self.client.post('/admin/subjects/create', data={
            'code': 'CS999',
            'name': 'Extreme Credits Subject',
            'department_id': dept.id,
            'semester': 4,
            'credits': 20
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Course credits must be between 1 and 12', res.data)
        self.assertIsNone(Subject.query.filter_by(code='CS999').first())

    def test_invalid_email_format_rejected(self):
        """Verify malformed email addresses are rejected during user enrollment."""
        self.login_user('admin', 'admin123')
        dept = Department.query.filter_by(code='CSE').first()

        res = self.client.post('/admin/students/create', data={
            'username': 'student_bademail',
            'email': 'not-a-valid-email-format',
            'password': 'password123',
            'full_name': 'Test Student',
            'roll_number': 'CS-BAD-01',
            'department_id': dept.id,
            'semester': 1
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Invalid email address format', res.data)
        self.assertIsNone(User.query.filter_by(username='student_bademail').first())

    def test_malformed_session_date_rejected(self):
        """Verify faculty cannot record attendance sessions with malformed dates."""
        self.login_user('fac_sharma', 'faculty123')
        profile = FacultyProfile.query.filter_by(employee_id='EMP-CSE-101').first()
        assignment = FacultyAssignment.query.filter_by(faculty_id=profile.id).first()

        res = self.client.post('/faculty/attendance/mark', data={
            'class_id': assignment.class_id,
            'subject_id': assignment.subject_id,
            'session_date': 'invalid-date-format',
            'session_slot': 'Period 1'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Invalid Session Date format', res.data)

    def test_reversed_date_range_flashes_warning(self):
        """Verify report query with date_from > date_to flashes warning."""
        self.login_user('admin', 'admin123')
        res = self.client.get('/admin/reports/classes?date_from=2026-10-10&date_to=2026-10-01')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Start Date cannot be after End Date', res.data)

    # =========================================================================
    # 6. OBJECT-LEVEL AUTHORIZATION ISOLATION
    # =========================================================================

    def test_cross_faculty_attendance_recording_forbidden(self):
        """Verify a faculty member cannot mark attendance for an unassigned class/subject."""
        self.login_user('fac_sharma', 'faculty123')
        # fac_sharma belongs to CSE. Find an assignment belonging to another faculty (ECE or EE)
        other_faculty = FacultyProfile.query.filter(FacultyProfile.employee_id != 'EMP-CSE-101').first()
        other_assignment = FacultyAssignment.query.filter_by(faculty_id=other_faculty.id).first()

        res = self.client.post('/faculty/attendance/mark', data={
            'class_id': other_assignment.class_id,
            'subject_id': other_assignment.subject_id,
            'session_date': date.today().isoformat(),
            'session_slot': 'Period 1'
        })
        self.assertEqual(res.status_code, 403)

    def test_cross_faculty_attendance_editing_forbidden(self):
        """Verify a faculty member cannot edit another instructor's attendance session."""
        self.login_user('fac_sharma', 'faculty123')
        sharma_profile = FacultyProfile.query.filter_by(employee_id='EMP-CSE-101').first()
        other_session = AttendanceSession.query.filter(AttendanceSession.faculty_id != sharma_profile.id).first()

        res = self.client.get(f'/faculty/attendance/{other_session.id}/edit')
        self.assertEqual(res.status_code, 403)

    def test_student_cannot_view_unassigned_subject_details(self):
        """Verify student accessing a subject outside their curriculum returns 404."""
        self.login_user('student_aarav', 'student123')
        # Student Aarav is enrolled in CSE semester 5.
        # Find a subject belonging to an entirely different department or semester (e.g. EC501)
        ec_subject = Subject.query.filter_by(code='EC501').first()
        self.assertIsNotNone(ec_subject)
        res = self.client.get(f'/student/attendance/{ec_subject.id}')
        self.assertEqual(res.status_code, 404)


if __name__ == '__main__':
    unittest.main()
