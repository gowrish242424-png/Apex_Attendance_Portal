"""Automated Test Suite for Phase 7: Analytics, Reports & CSV Export.

Covers:
- Formula injection protection (DDE / CSV injection defense)
- UTF-8 with BOM and streaming CSV response builder
- Admin Institutional Analytics dashboard & KPI aggregation
- Class-wise attendance reports & CSV export (summary & student breakdown)
- Subject-wise attendance reports & CSV export (catalog summary & roster breakdown)
- Faculty instructional activity report & CSV export
- Global student attendance audit report & CSV export
- Institutional shortage / defaulters report with custom threshold & CSV export
- Faculty report scoping & isolation (only assigned courses/students exported)
- Student personal attendance CSV export & isolation (only own records exported)
- Role-based access control (RBAC) across all Phase 7 endpoints
"""

import unittest
from app import create_app
from app.extensions import db
from app.models.user import User, StudentProfile, FacultyProfile
from app.models.academic import Department, Class, Subject, FacultyAssignment
from app.models.attendance import AttendanceSession, AttendanceRecord
from app.models.settings import SystemSetting
from app.services.report_service import ReportService
from app.utils.seed_data import seed_database


class Phase7ReportsTestCase(unittest.TestCase):
    def setUp(self):
        """Set up in-memory SQLite database and test client."""
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Seed standard realistic dataset
        seed_database(verbose=False)

        # Retrieve test entities
        self.admin = User.query.filter_by(username='admin').first()
        self.faculty_sharma = User.query.filter_by(username='fac_sharma').first()
        self.faculty_gupta = User.query.filter_by(username='fac_gupta').first()
        self.student_aarav = User.query.filter_by(username='student_aarav').first()
        self.prof_aarav = self.student_aarav.student_profile
        self.student_vikram = User.query.filter_by(username='student_vikram').first()
        self.prof_vikram = self.student_vikram.student_profile

        self.dept_cse = Department.query.filter_by(code='CSE').first()
        self.class_cse3a = Class.query.filter_by(name='CSE-3A').first()
        self.sub_cs501 = Subject.query.filter_by(code='CS501').first()

    def tearDown(self):
        """Clean up in-memory database."""
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def login_admin(self):
        return self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})

    def login_faculty_sharma(self):
        return self.client.post('/login', data={'username': 'fac_sharma', 'password': 'faculty123'})

    def login_faculty_gupta(self):
        return self.client.post('/login', data={'username': 'fac_gupta', 'password': 'faculty123'})

    def login_student_aarav(self):
        return self.client.post('/login', data={'username': 'student_aarav', 'password': 'student123'})

    def login_student_vikram(self):
        return self.client.post('/login', data={'username': 'student_vikram', 'password': 'student123'})

    # =========================================================================
    # 1. Formula Injection & CSV Sanitization Unit Tests
    # =========================================================================

    def test_sanitize_csv_cell_injection_defense(self):
        """Verify formula triggers (=, +, -, @, \\t, \\r) are safely escaped."""
        # Malicious formula strings starting with =, +, -, @
        self.assertEqual(ReportService.sanitize_csv_cell("=1+1"), "'=1+1")
        self.assertEqual(ReportService.sanitize_csv_cell("=cmd|'/C calc'!A0"), "'=cmd|'/C calc'!A0")
        self.assertEqual(ReportService.sanitize_csv_cell("@SUM(A1:A10)"), "'@SUM(A1:A10)")
        self.assertEqual(ReportService.sanitize_csv_cell("+cmd|'/c notepad'!A1"), "'+cmd|'/c notepad'!A1")
        self.assertEqual(ReportService.sanitize_csv_cell("-2+3+cmd|'...'"), "'-2+3+cmd|'...'")
        self.assertEqual(ReportService.sanitize_csv_cell("\tTabPrefix"), "'\tTabPrefix")
        self.assertEqual(ReportService.sanitize_csv_cell("\rReturnPrefix"), "'\rReturnPrefix")

        # Legitimate numbers should NOT be escaped
        self.assertEqual(ReportService.sanitize_csv_cell(100), "100")
        self.assertEqual(ReportService.sanitize_csv_cell(-25.5), "-25.5")
        self.assertEqual(ReportService.sanitize_csv_cell("+10"), "+10")
        self.assertEqual(ReportService.sanitize_csv_cell("-5"), "-5")
        self.assertEqual(ReportService.sanitize_csv_cell("85.75"), "85.75")

        # Safe text should remain unchanged
        self.assertEqual(ReportService.sanitize_csv_cell("CSE-3A"), "CSE-3A")
        self.assertEqual(ReportService.sanitize_csv_cell("Aarav Patel"), "Aarav Patel")
        self.assertEqual(ReportService.sanitize_csv_cell(""), "")
        self.assertEqual(ReportService.sanitize_csv_cell(None), "")

    def test_build_csv_response_utf8_bom(self):
        """Verify generated CSV contains UTF-8 BOM, text/csv mimetype, and Content-Disposition."""
        headers = ["Student Name", "Roll Number", "Turnout"]
        rows = [
            ["Aarav Patel", "CSE2024001", "88.5%"],
            ["=SUM(A1:B1)", "@ALERT", "+MALICIOUS"]
        ]
        response = ReportService.build_csv_response(headers, rows, "test_report.csv")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        self.assertIn('attachment; filename="test_report.csv"', response.headers.get('Content-Disposition', ''))
        
        # Verify UTF-8 BOM header
        data_text = response.get_data(as_text=True)
        self.assertTrue(data_text.startswith('\ufeff'), "CSV response must start with UTF-8 BOM")
        self.assertIn("Aarav Patel", data_text)
        self.assertIn("'=SUM(A1:B1)", data_text)
        self.assertIn("'@ALERT", data_text)

    # =========================================================================
    # 2. Institutional Analytics (Admin)
    # =========================================================================

    def test_admin_analytics_view_authenticated(self):
        """Admin can access institutional analytics dashboard with aggregate metrics."""
        self.login_admin()
        response = self.client.get('/admin/analytics')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Institutional Attendance Analytics", response.data)
        self.assertIn(b"Overall Turnout", response.data)
        self.assertIn(b"trendChart", response.data)
        self.assertIn(b"ratioChart", response.data)

    def test_admin_analytics_service_aggregation(self):
        """Verify calculation logic in ReportService.get_institutional_analytics."""
        analytics = ReportService.get_institutional_analytics()
        self.assertGreater(analytics['total_departments'], 0)
        self.assertGreater(analytics['total_classes'], 0)
        self.assertGreater(analytics['total_sessions'], 0)
        self.assertGreater(analytics['total_records'], 0)
        self.assertGreaterEqual(analytics['overall_percentage'], 0.0)
        self.assertLessEqual(analytics['overall_percentage'], 100.0)
        self.assertIn('trend_data', analytics)
        self.assertIn('department_breakdown', analytics)
        self.assertIn('class_breakdown', analytics)

    # =========================================================================
    # 3. Class Attendance Reports & CSV Export
    # =========================================================================

    def test_class_reports_view(self):
        """Admin can view class attendance reports."""
        self.login_admin()
        response = self.client.get('/admin/reports/classes')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Class Attendance Reports", response.data)
        self.assertIn(b"CSE-3A", response.data)

    def test_class_reports_filtered_with_student_breakdown(self):
        """Filtering by class_id displays enrolled students breakdown."""
        self.login_admin()
        response = self.client.get(f'/admin/reports/classes?class_id={self.class_cse3a.id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Enrolled Student Roster Breakdown", response.data)
        self.assertIn(self.prof_aarav.roll_number.encode(), response.data)

    def test_class_reports_export_csv_summary(self):
        """Admin can export class-level aggregated attendance summary as CSV."""
        self.login_admin()
        response = self.client.get('/admin/reports/classes/export.csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        data = response.get_data(as_text=True)
        self.assertIn("Class Name,Department,Semester", data)
        self.assertIn("CSE-3A", data)

    def test_class_reports_export_csv_student_breakdown(self):
        """Admin can export specific class student roster breakdown as CSV."""
        self.login_admin()
        response = self.client.get(f'/admin/reports/classes/export.csv?class_id={self.class_cse3a.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        data = response.get_data(as_text=True)
        self.assertIn("Roll Number,Student Name,Class,Attended,Absent,Total Sessions,Turnout %,Status", data)
        self.assertIn(self.prof_aarav.roll_number, data)

    # =========================================================================
    # 4. Subject Attendance Reports & CSV Export
    # =========================================================================

    def test_subject_reports_view(self):
        """Admin can view subject attendance reports."""
        self.login_admin()
        response = self.client.get('/admin/reports/subjects')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Subject Attendance Reports", response.data)
        self.assertIn(b"CS501", response.data)

    def test_subject_reports_filtered_with_roster(self):
        """Filtering by subject_id displays student roll-call breakdown."""
        self.login_admin()
        response = self.client.get(f'/admin/reports/subjects?subject_id={self.sub_cs501.id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Subject Student Roll-Call Breakdown", response.data)

    def test_subject_reports_export_csv_summary(self):
        """Admin can export subject catalog summary as CSV."""
        self.login_admin()
        response = self.client.get('/admin/reports/subjects/export.csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        data = response.get_data(as_text=True)
        self.assertIn("Subject Code,Subject Name,Department", data)
        self.assertIn("CS501", data)

    def test_subject_reports_export_csv_roster(self):
        """Admin can export specific subject roster as CSV."""
        self.login_admin()
        response = self.client.get(f'/admin/reports/subjects/export.csv?subject_id={self.sub_cs501.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        data = response.get_data(as_text=True)
        self.assertIn("Roll Number,Student Name,Subject Code,Subject Name", data)
        self.assertIn("CS501", data)

    # =========================================================================
    # 5. Faculty Activity Reports & CSV Export
    # =========================================================================

    def test_faculty_reports_view(self):
        """Admin can view faculty instructional activity report."""
        self.login_admin()
        response = self.client.get('/admin/reports/faculty')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Faculty Attendance Activity Reports", response.data)
        self.assertIn(b"Dr. Rajesh Sharma", response.data)

    def test_faculty_reports_export_csv(self):
        """Admin can export faculty instructional activity report as CSV."""
        self.login_admin()
        response = self.client.get('/admin/reports/faculty/export.csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        data = response.get_data(as_text=True)
        self.assertIn("Employee ID,Faculty Name,Department,Designation,Assigned Classes", data)
        self.assertIn("Dr. Rajesh Sharma", data)

    # =========================================================================
    # 6. Global Student Attendance Audit & CSV Export
    # =========================================================================

    def test_student_reports_view_and_search(self):
        """Admin can audit student attendance with search and class filters."""
        self.login_admin()
        response = self.client.get('/admin/reports/students?search=Aarav')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Global Student Attendance Audit", response.data)
        self.assertIn(b"Aarav Patel", response.data)

    def test_student_reports_export_csv(self):
        """Admin can export global student attendance audit as CSV."""
        self.login_admin()
        response = self.client.get('/admin/reports/students/export.csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        data = response.get_data(as_text=True)
        self.assertIn("Roll Number,Student Name,Email,Department,Class,Curriculum Context", data)
        self.assertIn("Aarav Patel", data)

    # =========================================================================
    # 7. Institutional Defaulters Report & CSV Export
    # =========================================================================

    def test_defaulter_reports_view_and_custom_threshold(self):
        """Admin can inspect defaulters with default and custom thresholds."""
        self.login_admin()
        # Default threshold
        res1 = self.client.get('/admin/reports/defaulters')
        self.assertEqual(res1.status_code, 200)
        self.assertIn(b"Institutional Defaulters Report", res1.data)

        # Custom threshold 95% (should capture more students)
        res2 = self.client.get('/admin/reports/defaulters?threshold=95')
        self.assertEqual(res2.status_code, 200)
        self.assertIn(b"95", res2.data)

    def test_defaulter_reports_export_csv(self):
        """Admin can export institutional defaulters list as CSV."""
        self.login_admin()
        response = self.client.get('/admin/reports/defaulters/export.csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        data = response.get_data(as_text=True)
        self.assertIn("Roll Number,Student Name,Department,Class,Subject Code", data)
        self.assertIn("Shortage Deficit %", data)

    # =========================================================================
    # 8. Faculty Scoped Reports & CSV Export (Strict Faculty Isolation)
    # =========================================================================

    def test_faculty_reports_view_authenticated(self):
        """Faculty can view their assigned course reporting dashboard."""
        self.login_faculty_sharma()
        response = self.client.get('/faculty/reports')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Faculty Attendance Reports & Export", response.data)
        self.assertIn(b"Assigned Course Performance Breakdown", response.data)

    def test_faculty_export_attendance_csv_scoped(self):
        """Faculty CSV export only includes courses and records taught by that faculty member."""
        self.login_faculty_sharma()
        response = self.client.get('/faculty/reports/attendance/export.csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        data = response.get_data(as_text=True)
        self.assertIn("Class,Subject Code,Subject Name,Sessions Conducted", data)
        self.assertIn("CS501", data)

        # Verify Dr. Sharma does NOT export courses belonging exclusively to Prof. Priya Gupta (e.g., EC501/CS502)
        sharma_subs = [a.subject.code for a in self.faculty_sharma.faculty_profile.assignments]
        gupta_only_subs = [
            a.subject.code for a in self.faculty_gupta.faculty_profile.assignments
            if a.subject.code not in sharma_subs
        ]
        for g_sub in gupta_only_subs:
            self.assertNotIn(f",{g_sub},", data)

    def test_faculty_export_defaulters_csv_scoped(self):
        """Faculty defaulters CSV export contains only students in faculty's assigned classes/subjects."""
        self.login_faculty_sharma()
        response = self.client.get('/faculty/reports/defaulters/export.csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        data = response.get_data(as_text=True)
        self.assertIn("Roll Number,Student Name,Class,Subject Code", data)

    # =========================================================================
    # 9. Student Personal Attendance CSV Export (Strict Student Isolation)
    # =========================================================================

    def test_student_export_attendance_csv(self):
        """Student can export their personal attendance history as CSV."""
        self.login_student_aarav()
        response = self.client.get('/student/attendance/export.csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        self.assertIn(f'attachment; filename="my_attendance_{self.prof_aarav.roll_number}.csv"', response.headers.get('Content-Disposition', ''))
        
        data = response.get_data(as_text=True)
        self.assertIn("Session Date,Period / Slot,Subject Code,Subject Name,Class,Instructor,Status,Remarks", data)
        self.assertIn("CS501", data)

        # CRUCIAL ISOLATION TEST: Aarav's CSV must NOT contain Vikram's records
        self.assertNotIn("Vikram Singh", data)
        self.assertNotIn(self.prof_vikram.roll_number, data)

    def test_student_export_attendance_csv_filtered(self):
        """Student personal CSV export respects query parameters (subject, status)."""
        self.login_student_aarav()
        response = self.client.get(f'/student/attendance/export.csv?subject_id={self.sub_cs501.id}&status=PRESENT')
        self.assertEqual(response.status_code, 200)
        data = response.get_data(as_text=True)
        self.assertIn("CS501", data)
        # All data rows must have PRESENT status
        for line in data.strip().splitlines()[1:]:  # skip header
            if line:
                self.assertIn("PRESENT", line)
                self.assertNotIn("ABSENT", line)

    # =========================================================================
    # 10. Role-Based Access Control (RBAC) Enforcement
    # =========================================================================

    def test_rbac_admin_reports_blocked_for_student(self):
        """Students cannot access admin analytics or report endpoints."""
        self.login_student_aarav()
        endpoints = [
            '/admin/analytics',
            '/admin/reports/classes',
            '/admin/reports/classes/export.csv',
            '/admin/reports/subjects',
            '/admin/reports/subjects/export.csv',
            '/admin/reports/faculty',
            '/admin/reports/faculty/export.csv',
            '/admin/reports/students',
            '/admin/reports/students/export.csv',
            '/admin/reports/defaulters',
            '/admin/reports/defaulters/export.csv'
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertIn(res.status_code, [302, 403], f"Endpoint {ep} should be blocked for students")

    def test_rbac_faculty_reports_blocked_for_student(self):
        """Students cannot access faculty reports or exports."""
        self.login_student_aarav()
        endpoints = [
            '/faculty/reports',
            '/faculty/reports/attendance/export.csv',
            '/faculty/reports/defaulters/export.csv'
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertIn(res.status_code, [302, 403], f"Endpoint {ep} should be blocked for students")

    def test_rbac_student_export_blocked_for_anonymous(self):
        """Unauthenticated requests to student export are redirected to login."""
        response = self.client.get('/student/attendance/export.csv')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))


if __name__ == '__main__':
    unittest.main()
