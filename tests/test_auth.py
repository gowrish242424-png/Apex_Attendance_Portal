import unittest
from app import create_app
from app.extensions import db
from app.models.user import User, StudentProfile, FacultyProfile
from app.models.academic import Department, Class
from app.utils.seed_data import seed_database

class Phase3AuthenticationTestCase(unittest.TestCase):
    def setUp(self):
        """Set up in-memory SQLite database and test client."""
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Seed realistic accounts for testing
        seed_database(verbose=False)

    def tearDown(self):
        """Clean up in-memory database."""
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    # ==================== Authentication Tests ====================

    def test_login_page_renders_200(self):
        """Verify GET /login returns HTTP 200 and displays login interface."""
        res = self.client.get('/login')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Sign In', res.data)
        self.assertIn(b'Apex Attendance Portal', res.data)
        self.assertIn(b'name="username"', res.data)
        self.assertIn(b'name="password"', res.data)

    def test_valid_admin_login(self):
        """Verify Admin credentials authenticate and redirect to /admin/dashboard."""
        res = self.client.post('/login', data={
            'username': 'admin',
            'password': 'admin123'
        }, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers['Location'].endswith('/admin/dashboard'))

        # Follow redirect and verify dashboard renders
        dash_res = self.client.get('/admin/dashboard')
        self.assertEqual(dash_res.status_code, 200)
        self.assertIn(b'System Control Portal', dash_res.data)
        self.assertIn(b'Administrator Role', dash_res.data)

    def test_valid_faculty_login(self):
        """Verify Faculty credentials authenticate and redirect to /faculty/dashboard."""
        res = self.client.post('/login', data={
            'username': 'fac_sharma',
            'password': 'faculty123'
        }, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers['Location'].endswith('/faculty/dashboard'))

        dash_res = self.client.get('/faculty/dashboard')
        self.assertEqual(dash_res.status_code, 200)
        self.assertIn(b'Dr. Rajesh Sharma', dash_res.data)
        self.assertIn(b'Faculty Role', dash_res.data)

    def test_valid_student_login(self):
        """Verify Student credentials authenticate and redirect to /student/dashboard."""
        res = self.client.post('/login', data={
            'username': 'student_aarav',
            'password': 'student123'
        }, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers['Location'].endswith('/student/dashboard'))

        dash_res = self.client.get('/student/dashboard')
        self.assertEqual(dash_res.status_code, 200)
        self.assertIn(b'Aarav Patel', dash_res.data)
        self.assertIn(b'Student Role', dash_res.data)

    def test_login_with_email_identifier(self):
        """Verify users can sign in using their registered email address."""
        res = self.client.post('/login', data={
            'username': 'admin@apex.edu',
            'password': 'admin123'
        }, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers['Location'].endswith('/admin/dashboard'))

    def test_invalid_password_rejected(self):
        """Verify invalid password returns HTTP 401 with informative error."""
        res = self.client.post('/login', data={
            'username': 'admin',
            'password': 'IncorrectPassword'
        })
        self.assertEqual(res.status_code, 401)
        self.assertIn(b'Invalid username or password', res.data)

    def test_non_existent_username_rejected(self):
        """Verify non-existent username returns HTTP 401."""
        res = self.client.post('/login', data={
            'username': 'unknown_user_99',
            'password': 'somepassword'
        })
        self.assertEqual(res.status_code, 401)
        self.assertIn(b'Invalid username or password', res.data)

    def test_empty_credentials_rejected(self):
        """Verify empty username or password returns HTTP 400."""
        res = self.client.post('/login', data={
            'username': '',
            'password': ''
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn(b'Please enter both username', res.data)

    def test_deactivated_account_rejected(self):
        """Verify deactivated accounts (is_active=False) cannot log in."""
        user = User.query.filter_by(username='student_aarav').first()
        user.is_active = False
        db.session.commit()

        res = self.client.post('/login', data={
            'username': 'student_aarav',
            'password': 'student123'
        })
        self.assertEqual(res.status_code, 403)
        self.assertIn(b'This account has been deactivated', res.data)

    def test_logout_terminates_session(self):
        """Verify logging out clears session and redirects to /login."""
        # Log in first
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})
        # Verify authenticated access
        self.assertEqual(self.client.get('/admin/dashboard').status_code, 200)

        # Log out
        res = self.client.get('/logout', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers['Location'].endswith('/login'))

        # Verify session is terminated
        dash_res = self.client.get('/admin/dashboard')
        self.assertEqual(dash_res.status_code, 302)
        self.assertIn('/login', dash_res.headers['Location'])

    def test_unauthenticated_access_redirects_to_login(self):
        """Verify unauthenticated requests to protected dashboards are redirected to /login."""
        for path in ['/admin/dashboard', '/faculty/dashboard', '/student/dashboard']:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 302)
            self.assertIn('/login', res.headers['Location'])

    def test_authenticated_user_redirected_from_login(self):
        """Verify authenticated user visiting /login is redirected to their dashboard."""
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})
        res = self.client.get('/login')
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers['Location'].endswith('/admin/dashboard'))

    # ==================== RBAC / Authorization Tests ====================

    def test_student_cannot_access_admin_dashboard(self):
        """Verify Student attempting to access /admin/dashboard receives HTTP 403 Forbidden."""
        self.client.post('/login', data={'username': 'student_aarav', 'password': 'student123'})
        res = self.client.get('/admin/dashboard')
        self.assertEqual(res.status_code, 403)
        self.assertIn(b'403 Forbidden', res.data)
        self.assertIn(b'Access Denied', res.data)

    def test_student_cannot_access_faculty_dashboard(self):
        """Verify Student attempting to access /faculty/dashboard receives HTTP 403 Forbidden."""
        self.client.post('/login', data={'username': 'student_aarav', 'password': 'student123'})
        res = self.client.get('/faculty/dashboard')
        self.assertEqual(res.status_code, 403)
        self.assertIn(b'403 Forbidden', res.data)

    def test_faculty_cannot_access_admin_dashboard(self):
        """Verify Faculty attempting to access /admin/dashboard receives HTTP 403 Forbidden."""
        self.client.post('/login', data={'username': 'fac_sharma', 'password': 'faculty123'})
        res = self.client.get('/admin/dashboard')
        self.assertEqual(res.status_code, 403)
        self.assertIn(b'403 Forbidden', res.data)

    def test_faculty_cannot_access_student_dashboard(self):
        """Verify Faculty attempting to access /student/dashboard receives HTTP 403 Forbidden."""
        self.client.post('/login', data={'username': 'fac_sharma', 'password': 'faculty123'})
        res = self.client.get('/student/dashboard')
        self.assertEqual(res.status_code, 403)
        self.assertIn(b'403 Forbidden', res.data)

    def test_admin_cannot_access_student_dashboard(self):
        """Verify Admin cannot access role-restricted Student dashboard."""
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})
        res = self.client.get('/student/dashboard')
        self.assertEqual(res.status_code, 403)
        self.assertIn(b'403 Forbidden', res.data)

    def test_custom_403_page_rendered_with_role_context(self):
        """Verify 403 page renders friendly message with the user's role."""
        self.client.post('/login', data={'username': 'student_aarav', 'password': 'student123'})
        res = self.client.get('/admin/dashboard')
        self.assertEqual(res.status_code, 403)
        self.assertIn(b'Student', res.data)
        self.assertIn(b'Return to Student Dashboard', res.data)

if __name__ == '__main__':
    unittest.main()
