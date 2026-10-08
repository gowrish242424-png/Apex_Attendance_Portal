import unittest
from datetime import date
from sqlalchemy.exc import IntegrityError
from app import create_app
from app.extensions import db
from app.models import (
    User, FacultyProfile, StudentProfile,
    Department, Class, Subject, FacultyAssignment,
    AttendanceSession, AttendanceRecord, SystemSetting
)

class Phase2ModelsTestCase(unittest.TestCase):
    def setUp(self):
        """Set up in-memory SQLite database for testing."""
        self.app = create_app('testing')
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        """Clean up and tear down in-memory database."""
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_model_imports(self):
        """Verify all 10 required models are correctly imported."""
        models = [
            User, FacultyProfile, StudentProfile,
            Department, Class, Subject, FacultyAssignment,
            AttendanceSession, AttendanceRecord, SystemSetting
        ]
        for m in models:
            self.assertIsNotNone(m)

    def test_database_tables_created(self):
        """Verify all expected database tables exist in SQLAlchemy metadata."""
        expected_tables = {
            'users', 'faculty_profiles', 'student_profiles',
            'departments', 'classes', 'subjects', 'faculty_assignments',
            'attendance_sessions', 'attendance_records', 'system_settings'
        }
        actual_tables = set(db.metadata.tables.keys())
        self.assertTrue(expected_tables.issubset(actual_tables))

    def test_user_password_hashing(self):
        """Verify password is hashed and not stored in plaintext."""
        user = User(username='test_user', email='test@example.com', role='student')
        user.set_password('SecretPassword123')
        db.session.add(user)
        db.session.commit()

        # Check hash is non-empty, not plain text, and matches check_password
        self.assertNotEqual(user.password_hash, 'SecretPassword123')
        self.assertTrue(user.password_hash.startswith(('scrypt:', 'pbkdf2:')))
        self.assertTrue(user.check_password('SecretPassword123'))
        self.assertFalse(user.check_password('WrongPassword'))

    def test_user_username_uniqueness(self):
        """Verify duplicate usernames raise an IntegrityError."""
        u1 = User(username='same_user', email='u1@example.com', role='student')
        u1.set_password('pass')
        db.session.add(u1)
        db.session.commit()

        u2 = User(username='same_user', email='u2@example.com', role='student')
        u2.set_password('pass')
        db.session.add(u2)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_academic_relationships(self):
        """Verify Department, Class, Subject, and Faculty relationships."""
        dept = Department(code='CSE', name='Computer Science')
        db.session.add(dept)
        db.session.commit()

        cls_obj = Class(name='CSE-3A', department_id=dept.id, semester=5, academic_year='2026-2027')
        sub = Subject(code='CS501', name='DBMS', department_id=dept.id, semester=5, credits=4)
        db.session.add_all([cls_obj, sub])
        db.session.commit()

        # Check reverse relationships
        self.assertEqual(len(dept.classes), 1)
        self.assertEqual(len(dept.subjects), 1)
        self.assertEqual(dept.classes[0].name, 'CSE-3A')
        self.assertEqual(dept.subjects[0].code, 'CS501')

    def test_duplicate_class_prevention(self):
        """Verify unique constraint on (name, department_id, academic_year)."""
        dept = Department(code='CSE', name='Computer Science')
        db.session.add(dept)
        db.session.commit()

        c1 = Class(name='CSE-3A', department_id=dept.id, semester=5, academic_year='2026-2027')
        db.session.add(c1)
        db.session.commit()

        c2 = Class(name='CSE-3A', department_id=dept.id, semester=5, academic_year='2026-2027')
        db.session.add(c2)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_faculty_assignment_uniqueness(self):
        """Verify faculty cannot be assigned twice to the same class/subject/year."""
        dept = Department(code='CSE', name='Computer Science')
        db.session.add(dept)
        db.session.commit()

        u = User(username='fac1', email='f1@example.com', role='faculty')
        u.set_password('pass')
        db.session.add(u)
        db.session.flush()

        fac = FacultyProfile(user_id=u.id, employee_id='EMP1', full_name='Dr. Smith', department_id=dept.id)
        cls_obj = Class(name='CSE-3A', department_id=dept.id, semester=5, academic_year='2026-2027')
        sub = Subject(code='CS501', name='DBMS', department_id=dept.id, semester=5)
        db.session.add_all([fac, cls_obj, sub])
        db.session.commit()

        a1 = FacultyAssignment(faculty_id=fac.id, class_id=cls_obj.id, subject_id=sub.id, academic_year='2026-2027')
        db.session.add(a1)
        db.session.commit()

        a2 = FacultyAssignment(faculty_id=fac.id, class_id=cls_obj.id, subject_id=sub.id, academic_year='2026-2027')
        db.session.add(a2)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_duplicate_attendance_record_prevention(self):
        """Verify unique constraint on (session_id, student_id) prevents duplicate marks."""
        dept = Department(code='CSE', name='Computer Science')
        db.session.add(dept)
        db.session.commit()

        cls_obj = Class(name='CSE-3A', department_id=dept.id, semester=5, academic_year='2026-2027')
        sub = Subject(code='CS501', name='DBMS', department_id=dept.id, semester=5)
        
        u_fac = User(username='fac1', email='f1@example.com', role='faculty')
        u_fac.set_password('pass')
        u_stu = User(username='stu1', email='s1@example.com', role='student')
        u_stu.set_password('pass')
        db.session.add_all([cls_obj, sub, u_fac, u_stu])
        db.session.flush()

        fac = FacultyProfile(user_id=u_fac.id, employee_id='EMP1', full_name='Dr. Smith', department_id=dept.id)
        stu = StudentProfile(user_id=u_stu.id, roll_number='ROLL01', full_name='Aarav', class_id=cls_obj.id, department_id=dept.id)
        db.session.add_all([fac, stu])
        db.session.commit()

        session = AttendanceSession(
            class_id=cls_obj.id, subject_id=sub.id, faculty_id=fac.id,
            session_date=date(2026, 10, 1), session_slot='Period 1'
        )
        db.session.add(session)
        db.session.commit()

        # First record: Present
        rec1 = AttendanceRecord(session_id=session.id, student_id=stu.id, status='PRESENT')
        db.session.add(rec1)
        db.session.commit()

        # Second record for same session & student: Must fail with IntegrityError
        rec2 = AttendanceRecord(session_id=session.id, student_id=stu.id, status='ABSENT')
        db.session.add(rec2)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_duplicate_attendance_session_prevention(self):
        """Verify unique constraint on (class_id, subject_id, session_date, session_slot)."""
        dept = Department(code='CSE', name='Computer Science')
        db.session.add(dept)
        db.session.commit()

        cls_obj = Class(name='CSE-3A', department_id=dept.id, semester=5, academic_year='2026-2027')
        sub = Subject(code='CS501', name='DBMS', department_id=dept.id, semester=5)
        u_fac = User(username='fac1', email='f1@example.com', role='faculty')
        u_fac.set_password('pass')
        db.session.add_all([cls_obj, sub, u_fac])
        db.session.flush()

        fac = FacultyProfile(user_id=u_fac.id, employee_id='EMP1', full_name='Dr. Smith', department_id=dept.id)
        db.session.add(fac)
        db.session.commit()

        s1 = AttendanceSession(
            class_id=cls_obj.id, subject_id=sub.id, faculty_id=fac.id,
            session_date=date(2026, 10, 1), session_slot='Period 1'
        )
        db.session.add(s1)
        db.session.commit()

        s2 = AttendanceSession(
            class_id=cls_obj.id, subject_id=sub.id, faculty_id=fac.id,
            session_date=date(2026, 10, 1), session_slot='Period 1'
        )
        db.session.add(s2)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_student_attendance_summary_calculation(self):
        """Verify attendance calculation helper handles 0 sessions and calculates correct percentage."""
        dept = Department(code='CSE', name='Computer Science')
        db.session.add(dept)
        db.session.commit()

        cls_obj = Class(name='CSE-3A', department_id=dept.id, semester=5, academic_year='2026-2027')
        sub = Subject(code='CS501', name='DBMS', department_id=dept.id, semester=5)
        u_fac = User(username='fac1', email='f1@example.com', role='faculty')
        u_fac.set_password('pass')
        u_stu = User(username='stu1', email='s1@example.com', role='student')
        u_stu.set_password('pass')
        db.session.add_all([cls_obj, sub, u_fac, u_stu])
        db.session.flush()

        fac = FacultyProfile(user_id=u_fac.id, employee_id='EMP1', full_name='Dr. Smith', department_id=dept.id)
        stu = StudentProfile(user_id=u_stu.id, roll_number='ROLL01', full_name='Aarav', class_id=cls_obj.id, department_id=dept.id)
        db.session.add_all([fac, stu])
        db.session.commit()

        # Zero sessions case
        summary0 = stu.get_attendance_summary()
        self.assertEqual(summary0['total'], 0)
        self.assertIsNone(summary0['percentage'])
        self.assertEqual(summary0['status'], 'Not Started')

        # Add 4 sessions: 3 Present, 1 Absent (75.0%)
        for i in range(4):
            sess = AttendanceSession(
                class_id=cls_obj.id, subject_id=sub.id, faculty_id=fac.id,
                session_date=date(2026, 10, i + 1), session_slot='Period 1'
            )
            db.session.add(sess)
            db.session.flush()
            rec = AttendanceRecord(
                session_id=sess.id,
                student_id=stu.id,
                status='PRESENT' if i < 3 else 'ABSENT'
            )
            db.session.add(rec)
        db.session.commit()

        summary = stu.get_attendance_summary()
        self.assertEqual(summary['total'], 4)
        self.assertEqual(summary['attended'], 3)
        self.assertEqual(summary['absent'], 1)
        self.assertEqual(summary['percentage'], 75.0)
        self.assertEqual(summary['status'], 'Eligible')

    def test_system_settings_helpers(self):
        """Verify SystemSetting class methods get_value, get_int, and set_value."""
        SystemSetting.set_value('min_attendance_threshold', 80, 'Custom threshold')
        self.assertEqual(SystemSetting.get_value('min_attendance_threshold'), '80')
        self.assertEqual(SystemSetting.get_int('min_attendance_threshold'), 80)
        self.assertEqual(SystemSetting.get_int('non_existent', default=75), 75)

if __name__ == '__main__':
    unittest.main()
