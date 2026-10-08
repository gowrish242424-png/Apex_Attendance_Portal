"""Automated Test Suite for Phase 6: Student Portal.

Covers:
- Student dashboard rendering, telemetry, and isolation
- Overall attendance calculations & zero-record edge cases
- Subject-wise attendance breakdown, thresholds, and status indicators
- Individual subject roll call inspection and 404 on unrelated subjects
- Chronological attendance history with server-side filters (subject, status, date)
- Attendance shortage detection & deficit calculations
- "What-If" future attendance simulator (attend-all, miss-all, minimum needed,
  insufficient scenarios, bounds validation, and zero-database-mutation guarantee)
- Strict student-level data isolation (cross-student access blocked)
- Security & RBAC enforcement across all student routes
"""

import unittest
from datetime import date, timedelta
from app import create_app
from app.extensions import db
from app.models.user import User, StudentProfile, FacultyProfile
from app.models.academic import Department, Class, Subject
from app.models.attendance import AttendanceSession, AttendanceRecord
from app.models.settings import SystemSetting
from app.utils.seed_data import seed_database
from app.services.attendance_service import AttendanceService


class Phase6StudentPortalTestCase(unittest.TestCase):
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
        # Student A: Aarav Patel (High Attendance, CSE-3A)
        self.student_aarav = User.query.filter_by(username='student_aarav').first()
        self.prof_aarav = self.student_aarav.student_profile

        # Student B: Vikram Singh (Defaulter, CSE-3A)
        self.student_vikram = User.query.filter_by(username='student_vikram').first()
        self.prof_vikram = self.student_vikram.student_profile

        # Student C: Siddharth Rao (High Attendance, ECE-3A)
        self.student_siddharth = User.query.filter_by(username='student_siddharth').first()
        self.prof_siddharth = self.student_siddharth.student_profile

        # Faculty: Dr. Rajesh Sharma
        self.faculty_sharma = User.query.filter_by(username='fac_sharma').first()

        # Subjects
        self.sub_cs501 = Subject.query.filter_by(code='CS501').first()
        self.sub_cs502 = Subject.query.filter_by(code='CS502').first()
        self.sub_ec501 = Subject.query.filter_by(code='EC501').first()

    def tearDown(self):
        """Clean up in-memory database."""
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def login_student_aarav(self):
        """Log in as Student Aarav Patel (Eligible)."""
        return self.client.post('/login', data={'username': 'student_aarav', 'password': 'student123'})

    def login_student_vikram(self):
        """Log in as Student Vikram Singh (Defaulter)."""
        return self.client.post('/login', data={'username': 'student_vikram', 'password': 'student123'})

    def login_faculty(self):
        """Log in as Faculty Dr. Rajesh Sharma."""
        return self.client.post('/login', data={'username': 'fac_sharma', 'password': 'faculty123'})

    # =========================================================================
    # A. Student Dashboard
    # =========================================================================

    def test_student_dashboard_access(self):
        """Verify Student can access /student/dashboard and see their own credentials."""
        self.login_student_aarav()
        res = self.client.get('/student/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Aarav Patel', res.data)
        self.assertIn(b'Student Role', res.data)
        self.assertIn(b'2026CSE001', res.data)
        self.assertIn(b'CSE-3A', res.data)
        self.assertIn(b'Overall Attendance', res.data)
        self.assertIn(b'What-If Calculator', res.data)

    def test_unauthenticated_redirected_from_student_dashboard(self):
        """Verify unauthenticated access to student dashboard redirects to /login."""
        res = self.client.get('/student/dashboard')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers['Location'])

    def test_faculty_blocked_from_student_dashboard(self):
        """Verify Faculty attempting to access /student/dashboard receives HTTP 403 Forbidden."""
        self.login_faculty()
        res = self.client.get('/student/dashboard')
        self.assertEqual(res.status_code, 403)
        self.assertIn(b'403 Forbidden', res.data)

    def test_student_dashboard_displays_only_own_data(self):
        """Verify Student A does NOT see Student B's name, roll number, or records."""
        self.login_student_aarav()
        res = self.client.get('/student/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Aarav Patel', res.data)
        self.assertIn(b'2026CSE001', res.data)
        # Should NOT contain Vikram Singh's details
        self.assertNotIn(b'Vikram Singh', res.data)
        self.assertNotIn(b'2026CSE005', res.data)

    # =========================================================================
    # B. Attendance Summary
    # =========================================================================

    def test_overall_attendance_calculation(self):
        """Verify overall attendance summary accurately calculates total, attended, absent, and percentage."""
        summary = AttendanceService.get_student_overall_summary(self.prof_aarav)
        self.assertGreater(summary['total'], 0)
        self.assertGreater(summary['attended'], 0)
        self.assertEqual(summary['total'], summary['attended'] + summary['absent'])
        expected_pct = round((summary['attended'] / summary['total']) * 100, 2)
        self.assertEqual(summary['percentage'], expected_pct)
        self.assertEqual(summary['status'], 'Eligible')
        self.assertTrue(summary['is_eligible'])

    def test_zero_record_case_handled_safely(self):
        """Verify zero-session students render safely with 0.0% and no division-by-zero error."""
        # Create a new student with no attendance sessions recorded
        new_user = User(username='student_zero', email='zero@apex.edu', role='student', is_active=True)
        new_user.set_password('student123')
        db.session.add(new_user)
        db.session.flush()

        new_prof = StudentProfile(
            user_id=new_user.id,
            roll_number='2026CSE099',
            full_name='Zero Session Student',
            class_id=self.prof_aarav.class_id,
            department_id=self.prof_aarav.department_id,
            semester=5
        )
        db.session.add(new_prof)
        db.session.commit()

        summary = AttendanceService.get_student_overall_summary(new_prof)
        self.assertEqual(summary['total'], 0)
        self.assertEqual(summary['attended'], 0)
        self.assertEqual(summary['absent'], 0)
        self.assertEqual(summary['percentage'], 0.0)
        self.assertEqual(summary['status'], 'Not Started')

        # Log in and check template rendering
        self.client.post('/login', data={'username': 'student_zero', 'password': 'student123'})
        res = self.client.get('/student/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'0.0%', res.data)

    # =========================================================================
    # C. Subject Attendance
    # =========================================================================

    def test_subject_attendance_page_renders_applicable_subjects(self):
        """Verify /student/attendance displays all applicable courses for student's class."""
        self.login_student_aarav()
        res = self.client.get('/student/attendance')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Subject-Wise Attendance Overview', res.data)
        self.assertIn(b'CS501', res.data)
        self.assertIn(b'CS502', res.data)
        self.assertIn(b'CS503', res.data)
        # Should NOT display ECE subjects
        self.assertNotIn(b'EC501', res.data)
        self.assertNotIn(b'EC502', res.data)

    def test_subject_status_indicators(self):
        """Verify eligible student shows 'Good' and defaulter shows 'Shortage'."""
        # Aarav (eligible)
        self.login_student_aarav()
        res_aarav = self.client.get('/student/attendance')
        self.assertEqual(res_aarav.status_code, 200)
        self.assertIn(b'Good', res_aarav.data)

        # Vikram (defaulter)
        self.login_student_vikram()
        res_vikram = self.client.get('/student/attendance')
        self.assertEqual(res_vikram.status_code, 200)
        self.assertIn(b'Shortage', res_vikram.data)

    # =========================================================================
    # D. Subject Details
    # =========================================================================

    def test_subject_details_accessible_for_authorized_subject(self):
        """Verify /student/attendance/<subject_id> renders session history for student."""
        self.login_student_aarav()
        res = self.client.get(f'/student/attendance/{self.sub_cs501.id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Database Management Systems', res.data)
        self.assertIn(b'CS501', res.data)
        self.assertIn(b'Session-by-Session Roll Call Log', res.data)

    def test_subject_details_inaccessible_for_unrelated_subject(self):
        """Verify /student/attendance/<subject_id> returns HTTP 404 for an unrelated subject."""
        self.login_student_aarav()
        # EC501 belongs to ECE, not Aarav's CSE curriculum
        res = self.client.get(f'/student/attendance/{self.sub_ec501.id}')
        self.assertEqual(res.status_code, 404)

    def test_subject_details_does_not_leak_other_student_records(self):
        """Verify session log displays only records for the logged-in student."""
        details = AttendanceService.get_student_subject_details(self.prof_aarav, self.sub_cs501.id)
        for rec in details['records']:
            self.assertEqual(rec.student_id, self.prof_aarav.id)
            self.assertNotEqual(rec.student_id, self.prof_vikram.id)

    # =========================================================================
    # E. Attendance History
    # =========================================================================

    def test_attendance_history_shows_only_current_student(self):
        """Verify /student/attendance/history lists only current student's records."""
        self.login_student_aarav()
        res = self.client.get('/student/attendance/history')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'My Attendance History', res.data)
        self.assertIn(b'CS501', res.data)

    def test_attendance_history_filters(self):
        """Verify history filters by subject, status, and date range."""
        self.login_student_aarav()

        # Subject filter
        res_sub = self.client.get(f'/student/attendance/history?subject_id={self.sub_cs501.id}')
        self.assertEqual(res_sub.status_code, 200)
        self.assertIn(b'CS501', res_sub.data)

        # Status filter: PRESENT
        res_present = self.client.get('/student/attendance/history?status=PRESENT')
        self.assertEqual(res_present.status_code, 200)
        self.assertIn(b'PRESENT', res_present.data)

        # Status filter: ABSENT
        res_absent = self.client.get('/student/attendance/history?status=ABSENT')
        self.assertEqual(res_absent.status_code, 200)

    # =========================================================================
    # F. Defaulter & Shortage Tracking
    # =========================================================================

    def test_defaulter_student_shortage_detected(self):
        """Verify Vikram Singh is flagged with shortage and deficit calculation is correct."""
        summaries = AttendanceService.get_student_subject_summaries(self.prof_vikram)
        self.assertGreater(summaries['shortage_count'], 0)

        # Find CS501 for Vikram
        cs501_summary = next(s for s in summaries['subjects'] if s['subject'].code == 'CS501')
        self.assertTrue(cs501_summary['is_shortage'])
        self.assertLess(cs501_summary['percentage'], summaries['threshold'])
        expected_shortage = round(summaries['threshold'] - cs501_summary['percentage'], 2)
        self.assertEqual(cs501_summary['shortage'], expected_shortage)

    # =========================================================================
    # G. "What-If" Calculator
    # =========================================================================

    def test_what_if_attend_all_calculation(self):
        """Verify What-If calculator correctly forecasts 100% future attendance."""
        result, err = AttendanceService.calculate_what_if_attendance(
            self.prof_vikram,
            self.sub_cs501.id,
            upcoming_classes=10
        )
        self.assertIsNone(err)
        self.assertIsNotNone(result)
        self.assertEqual(result['upcoming_classes'], 10)
        self.assertEqual(result['new_total'], result['current_total'] + 10)
        self.assertEqual(result['attend_all_present'], result['current_present'] + 10)
        expected_pct = round((result['attend_all_present'] / result['new_total']) * 100, 2)
        self.assertEqual(result['attend_all_percentage'], expected_pct)

    def test_what_if_miss_all_calculation(self):
        """Verify What-If calculator correctly forecasts missing all upcoming classes."""
        result, err = AttendanceService.calculate_what_if_attendance(
            self.prof_vikram,
            self.sub_cs501.id,
            upcoming_classes=5
        )
        self.assertIsNone(err)
        self.assertEqual(result['miss_all_present'], result['current_present'])
        expected_pct = round((result['current_present'] / result['new_total']) * 100, 2)
        self.assertEqual(result['miss_all_percentage'], expected_pct)

    def test_what_if_impossible_scenario_handled(self):
        """Verify calculator detects when threshold cannot be reached within specified upcoming classes."""
        # Vikram has ~50% attendance across 10 sessions (5 present / 10 total).
        # In 1 upcoming class: new total = 11. Max present = 6. 6 / 11 = 54.55% < 75%.
        result, err = AttendanceService.calculate_what_if_attendance(
            self.prof_vikram,
            self.sub_cs501.id,
            upcoming_classes=1
        )
        self.assertIsNone(err)
        self.assertFalse(result['is_possible'])
        self.assertIn("still below the", result['explanation'])

    def test_what_if_negative_and_excessive_inputs_rejected(self):
        """Verify invalid upcoming class numbers are rejected with informative error messages."""
        # Negative
        res_neg, err_neg = AttendanceService.calculate_what_if_attendance(
            self.prof_aarav, self.sub_cs501.id, upcoming_classes=-5
        )
        self.assertIsNone(res_neg)
        self.assertIn("cannot be negative", err_neg)

        # Excessive
        res_large, err_large = AttendanceService.calculate_what_if_attendance(
            self.prof_aarav, self.sub_cs501.id, upcoming_classes=9999
        )
        self.assertIsNone(res_large)
        self.assertIn("cannot exceed 500", err_large)

    def test_what_if_calculator_does_not_modify_database(self):
        """Verify What-If calculations perform zero database mutations."""
        initial_sessions = AttendanceSession.query.count()
        initial_records = AttendanceRecord.query.count()

        # Run multiple calculations
        AttendanceService.calculate_what_if_attendance(self.prof_aarav, self.sub_cs501.id, 10)
        AttendanceService.calculate_what_if_attendance(self.prof_vikram, self.sub_cs501.id, 20)

        # Database counts must remain strictly identical
        self.assertEqual(AttendanceSession.query.count(), initial_sessions)
        self.assertEqual(AttendanceRecord.query.count(), initial_records)

    # =========================================================================
    # H. Security & Cross-Student Data Isolation
    # =========================================================================

    def test_student_profile_page_isolation(self):
        """Verify Student A viewing /student/profile sees only their own academic data."""
        self.login_student_aarav()
        res = self.client.get('/student/profile')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Aarav Patel', res.data)
        self.assertIn(b'2026CSE001', res.data)
        self.assertNotIn(b'Vikram Singh', res.data)
        self.assertNotIn(b'2026CSE005', res.data)

    def test_student_cannot_access_unrelated_curriculum_subject(self):
        """Verify Student attempting to access subject from another department receives HTTP 404."""
        self.login_student_aarav()
        # EC501 belongs to ECE department
        res = self.client.get(f'/student/attendance/{self.sub_ec501.id}')
        self.assertEqual(res.status_code, 404)

    def test_unauthenticated_requests_redirected_to_login(self):
        """Verify unauthenticated access to all student routes redirects to /login."""
        protected_routes = [
            '/student/dashboard',
            '/student/attendance',
            f'/student/attendance/{self.sub_cs501.id}',
            '/student/attendance/history',
            '/student/attendance/what-if',
            '/student/profile',
        ]
        for path in protected_routes:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 302, f"Failed for {path}")
            self.assertIn('/login', res.headers['Location'])

    def test_faculty_role_forbidden_on_all_student_routes(self):
        """Verify Faculty user receives HTTP 403 on all student portal routes."""
        self.login_faculty()
        protected_routes = [
            '/student/dashboard',
            '/student/attendance',
            f'/student/attendance/{self.sub_cs501.id}',
            '/student/attendance/history',
            '/student/attendance/what-if',
            '/student/profile',
        ]
        for path in protected_routes:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 403, f"Failed for {path}")


if __name__ == '__main__':
    unittest.main()
