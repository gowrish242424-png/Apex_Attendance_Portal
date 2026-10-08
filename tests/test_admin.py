import unittest
from app import create_app
from app.extensions import db
from app.models.user import User, FacultyProfile, StudentProfile
from app.models.academic import Department, Class, Subject, FacultyAssignment
from app.models.attendance import AttendanceSession, AttendanceRecord
from app.utils.seed_data import seed_database

class Phase4AdminGovernanceTestCase(unittest.TestCase):
    def setUp(self):
        """Set up in-memory SQLite database and test client."""
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Seed realistic base data
        seed_database(verbose=False)

    def tearDown(self):
        """Clean up in-memory database."""
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def login_admin(self):
        """Helper to log in as administrator."""
        return self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})

    def login_faculty(self):
        """Helper to log in as faculty member."""
        return self.client.post('/login', data={'username': 'fac_sharma', 'password': 'faculty123'})

    def login_student(self):
        """Helper to log in as student."""
        return self.client.post('/login', data={'username': 'student_aarav', 'password': 'student123'})

    # ==================== 1. Dashboard ====================

    def test_admin_dashboard_metrics(self):
        """Verify Admin dashboard renders telemetry and navigation."""
        self.login_admin()
        res = self.client.get('/admin/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Departments', res.data)
        self.assertIn(b'Classes', res.data)
        self.assertIn(b'Subjects', res.data)
        self.assertIn(b'Faculty', res.data)
        self.assertIn(b'Students', res.data)
        self.assertIn(b'Course Allocations', res.data)

    # ==================== 2. Department Management ====================

    def test_admin_view_departments(self):
        """Verify Admin can view departments list."""
        self.login_admin()
        res = self.client.get('/admin/departments')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'CSE', res.data)
        self.assertIn(b'Computer Science', res.data)

    def test_admin_create_department_success(self):
        """Verify Admin can create a new department."""
        self.login_admin()
        res = self.client.post('/admin/departments/create', data={
            'code': 'MECH',
            'name': 'Mechanical Engineering',
            'description': 'Department of Mechanical Engineering'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'MECH', res.data)
        self.assertIsNotNone(Department.query.filter_by(code='MECH').first())

    def test_admin_create_duplicate_department_rejected(self):
        """Verify duplicate department code is rejected with warning."""
        self.login_admin()
        res = self.client.post('/admin/departments/create', data={
            'code': 'CSE',
            'name': 'Duplicate Computer Science',
            'description': 'Test'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'already exists', res.data)

    def test_admin_edit_department(self):
        """Verify Admin can edit department details."""
        self.login_admin()
        dept = Department.query.filter_by(code='CSE').first()
        res = self.client.post(f'/admin/departments/{dept.id}/edit', data={
            'code': 'CSE',
            'name': 'Computer Science & AI',
            'description': 'Updated'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(dept.name, 'Computer Science & AI')

    def test_admin_unsafe_department_delete_blocked(self):
        """Verify department with existing classes/students cannot be deleted."""
        self.login_admin()
        dept = Department.query.filter_by(code='CSE').first()
        res = self.client.post(f'/admin/departments/{dept.id}/delete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Cannot delete department', res.data)
        self.assertIsNotNone(Department.query.filter_by(code='CSE').first())

    def test_admin_safe_department_delete_succeeds(self):
        """Verify unreferenced department can be safely deleted."""
        self.login_admin()
        dept = Department(code='CIVIL', name='Civil Engineering')
        db.session.add(dept)
        db.session.commit()

        res = self.client.post(f'/admin/departments/{dept.id}/delete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'deleted successfully', res.data)
        self.assertIsNone(Department.query.filter_by(code='CIVIL').first())

    # ==================== 3. Class Management ====================

    def test_admin_create_class_success(self):
        """Verify Admin can create a new class."""
        self.login_admin()
        dept = Department.query.filter_by(code='CSE').first()
        res = self.client.post('/admin/classes/create', data={
            'name': 'CSE-4A',
            'department_id': dept.id,
            'semester': 7,
            'academic_year': '2026-2027'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'CSE-4A', res.data)
        self.assertIsNotNone(Class.query.filter_by(name='CSE-4A').first())

    def test_admin_duplicate_class_rejected(self):
        """Verify duplicate class within the same department and year is rejected."""
        self.login_admin()
        dept = Department.query.filter_by(code='CSE').first()
        res = self.client.post('/admin/classes/create', data={
            'name': 'CSE-3A',
            'department_id': dept.id,
            'semester': 5,
            'academic_year': '2026-2027'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'already exists', res.data)

    def test_admin_class_filter_by_department(self):
        """Verify filtering classes by department."""
        self.login_admin()
        dept_cse = Department.query.filter_by(code='CSE').first()
        res = self.client.get(f'/admin/classes?department_id={dept_cse.id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'CSE-3A', res.data)

    def test_admin_unsafe_class_delete_blocked(self):
        """Verify class with enrolled students cannot be deleted."""
        self.login_admin()
        cls_obj = Class.query.filter_by(name='CSE-3A').first()
        res = self.client.post(f'/admin/classes/{cls_obj.id}/delete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Cannot delete class', res.data)
        self.assertIsNotNone(Class.query.filter_by(name='CSE-3A').first())

    # ==================== 4. Subject Management ====================

    def test_admin_create_subject_success(self):
        """Verify Admin can add a curriculum subject."""
        self.login_admin()
        dept = Department.query.filter_by(code='CSE').first()
        res = self.client.post('/admin/subjects/create', data={
            'code': 'CS504',
            'name': 'Software Engineering',
            'department_id': dept.id,
            'semester': 5,
            'credits': 3
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'CS504', res.data)
        self.assertIsNotNone(Subject.query.filter_by(code='CS504').first())

    def test_admin_duplicate_subject_rejected(self):
        """Verify duplicate subject code is rejected."""
        self.login_admin()
        dept = Department.query.filter_by(code='CSE').first()
        res = self.client.post('/admin/subjects/create', data={
            'code': 'CS501',
            'name': 'Duplicate DBMS',
            'department_id': dept.id,
            'semester': 5,
            'credits': 4
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'already exists', res.data)

    def test_admin_unsafe_subject_delete_blocked(self):
        """Verify subject with attendance records or allocations cannot be deleted."""
        self.login_admin()
        sub = Subject.query.filter_by(code='CS501').first()
        res = self.client.post(f'/admin/subjects/{sub.id}/delete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Cannot delete subject', res.data)
        self.assertIsNotNone(Subject.query.filter_by(code='CS501').first())

    # ==================== 5. Faculty Management ====================

    def test_admin_create_faculty_success(self):
        """Verify Admin can onboard faculty, creating User + Profile with hashed password."""
        self.login_admin()
        dept = Department.query.filter_by(code='CSE').first()
        res = self.client.post('/admin/faculty/create', data={
            'username': 'fac_menon',
            'email': 'menon@apex.edu',
            'password': 'facultySecure123',
            'full_name': 'Dr. Sunita Menon',
            'employee_id': 'EMP-CSE-109',
            'department_id': dept.id,
            'designation': 'Associate Professor',
            'phone': '9812345678'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Dr. Sunita Menon', res.data)

        # Verify database entity & password hashing
        user = User.query.filter_by(username='fac_menon').first()
        self.assertIsNotNone(user)
        self.assertEqual(user.role, 'faculty')
        self.assertTrue(user.check_password('facultySecure123'))
        self.assertNotEqual(user.password_hash, 'facultySecure123')

        profile = FacultyProfile.query.filter_by(employee_id='EMP-CSE-109').first()
        self.assertIsNotNone(profile)
        self.assertEqual(profile.user_id, user.id)

    def test_admin_duplicate_faculty_username_rejected(self):
        """Verify duplicate faculty username is rejected."""
        self.login_admin()
        res = self.client.post('/admin/faculty/create', data={
            'username': 'fac_sharma',  # Already exists in seed
            'email': 'unique_email@apex.edu',
            'password': 'pwd',
            'full_name': 'Another Sharma',
            'employee_id': 'EMP-NEW',
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'already taken', res.data)

    def test_admin_toggle_faculty_status(self):
        """Verify Admin can activate and deactivate faculty accounts."""
        self.login_admin()
        fac = FacultyProfile.query.filter_by(employee_id='EMP-CSE-101').first()
        self.assertTrue(fac.user.is_active)

        # Deactivate
        self.client.post(f'/admin/faculty/{fac.id}/toggle-status', follow_redirects=True)
        self.assertFalse(fac.user.is_active)

        # Reactivate
        self.client.post(f'/admin/faculty/{fac.id}/toggle-status', follow_redirects=True)
        self.assertTrue(fac.user.is_active)

    def test_admin_unsafe_faculty_delete_blocked(self):
        """Verify faculty with recorded attendance sessions cannot be deleted."""
        self.login_admin()
        fac = FacultyProfile.query.filter_by(employee_id='EMP-CSE-101').first()
        res = self.client.post(f'/admin/faculty/{fac.id}/delete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Cannot delete', res.data)
        self.assertIsNotNone(FacultyProfile.query.filter_by(employee_id='EMP-CSE-101').first())

    # ==================== 6. Student Management ====================

    def test_admin_create_student_success(self):
        """Verify Admin can enroll student, creating User + Profile with hashed password."""
        self.login_admin()
        cls_obj = Class.query.filter_by(name='CSE-3A').first()
        res = self.client.post('/admin/students/create', data={
            'username': 'student_kavita',
            'email': 'kavita@apex.edu',
            'password': 'studentPass123',
            'full_name': 'Kavita Iyer',
            'roll_number': '2026CSE099',
            'class_id': cls_obj.id,
            'department_id': cls_obj.department_id,
            'semester': 5,
            'phone': '9899887766'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Kavita Iyer', res.data)

        user = User.query.filter_by(username='student_kavita').first()
        self.assertIsNotNone(user)
        self.assertEqual(user.role, 'student')
        self.assertTrue(user.check_password('studentPass123'))

        profile = StudentProfile.query.filter_by(roll_number='2026CSE099').first()
        self.assertIsNotNone(profile)
        self.assertEqual(profile.user_id, user.id)

    def test_admin_duplicate_student_roll_rejected(self):
        """Verify duplicate roll number is rejected."""
        self.login_admin()
        res = self.client.post('/admin/students/create', data={
            'username': 'unique_student',
            'email': 'unique_student@apex.edu',
            'password': 'pwd',
            'full_name': 'Test',
            'roll_number': '2026CSE001',  # Already exists in seed
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'already exists', res.data)

    def test_admin_toggle_student_status(self):
        """Verify Admin can activate/deactivate student accounts."""
        self.login_admin()
        stu = StudentProfile.query.filter_by(roll_number='2026CSE001').first()
        self.assertTrue(stu.user.is_active)

        # Deactivate
        self.client.post(f'/admin/students/{stu.id}/toggle-status', follow_redirects=True)
        self.assertFalse(stu.user.is_active)

        # Reactivate
        self.client.post(f'/admin/students/{stu.id}/toggle-status', follow_redirects=True)
        self.assertTrue(stu.user.is_active)

    def test_admin_unsafe_student_delete_blocked(self):
        """Verify student with historical attendance marks cannot be deleted."""
        self.login_admin()
        stu = StudentProfile.query.filter_by(roll_number='2026CSE001').first()
        res = self.client.post(f'/admin/students/{stu.id}/delete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Cannot delete', res.data)
        self.assertIsNotNone(StudentProfile.query.filter_by(roll_number='2026CSE001').first())

    # ==================== 7. Course Allocation ====================

    def test_admin_create_allocation_success(self):
        """Verify Admin can allocate a faculty to a class and subject."""
        self.login_admin()
        fac = FacultyProfile.query.filter_by(employee_id='EMP-CSE-102').first()
        cls_obj = Class.query.filter_by(name='CSE-3A').first()
        sub = Subject.query.filter_by(code='CS503').first()

        # Remove if existing, then create
        existing = FacultyAssignment.query.filter_by(
            faculty_id=fac.id, class_id=cls_obj.id, subject_id=sub.id, academic_year='2026-2027'
        ).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()

        res = self.client.post('/admin/allocations/create', data={
            'faculty_id': fac.id,
            'class_id': cls_obj.id,
            'subject_id': sub.id,
            'academic_year': '2026-2027'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Successfully allocated', res.data)

    def test_admin_duplicate_allocation_rejected(self):
        """Verify duplicate course allocation is prevented."""
        self.login_admin()
        alloc = FacultyAssignment.query.first()
        res = self.client.post('/admin/allocations/create', data={
            'faculty_id': alloc.faculty_id,
            'class_id': alloc.class_id,
            'subject_id': alloc.subject_id,
            'academic_year': alloc.academic_year
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Allocation already exists', res.data)

    def test_admin_delete_allocation_success(self):
        """Verify Admin can remove an existing course allocation."""
        self.login_admin()
        alloc = FacultyAssignment.query.first()
        alloc_id = alloc.id
        res = self.client.post(f'/admin/allocations/{alloc_id}/delete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'removed successfully', res.data)
        self.assertIsNone(db.session.get(FacultyAssignment, alloc_id))

    # ==================== 8. Security & RBAC Enforcement ====================

    def test_unauthenticated_cannot_access_admin_governance(self):
        """Verify unauthenticated requests redirect to /login."""
        admin_urls = [
            '/admin/dashboard',
            '/admin/departments',
            '/admin/classes',
            '/admin/subjects',
            '/admin/faculty',
            '/admin/students',
            '/admin/allocations'
        ]
        for url in admin_urls:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302)
            self.assertIn('/login', res.headers['Location'])

    def test_faculty_cannot_access_admin_governance(self):
        """Verify Faculty user receives 403 Forbidden on all Admin governance routes."""
        self.login_faculty()
        admin_urls = [
            '/admin/dashboard',
            '/admin/departments',
            '/admin/classes',
            '/admin/subjects',
            '/admin/faculty',
            '/admin/students',
            '/admin/allocations'
        ]
        for url in admin_urls:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 403)
            self.assertIn(b'403 Forbidden', res.data)

    def test_student_cannot_access_admin_governance(self):
        """Verify Student user receives 403 Forbidden on all Admin governance routes."""
        self.login_student()
        admin_urls = [
            '/admin/dashboard',
            '/admin/departments',
            '/admin/classes',
            '/admin/subjects',
            '/admin/faculty',
            '/admin/students',
            '/admin/allocations'
        ]
        for url in admin_urls:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 403)
            self.assertIn(b'403 Forbidden', res.data)

    def test_student_cannot_post_admin_actions(self):
        """Verify non-admin cannot submit destructive POST requests to admin routes."""
        self.login_student()
        res = self.client.post('/admin/departments/create', data={
            'code': 'HACK',
            'name': 'Unauthorized Dept'
        })
        self.assertEqual(res.status_code, 403)
        self.assertIsNone(Department.query.filter_by(code='HACK').first())

if __name__ == '__main__':
    unittest.main()
