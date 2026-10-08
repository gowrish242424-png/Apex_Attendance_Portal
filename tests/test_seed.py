import unittest
from app import create_app
from app.extensions import db
from app.models import (
    User, FacultyProfile, StudentProfile,
    Department, Class, Subject, FacultyAssignment,
    AttendanceSession, AttendanceRecord, SystemSetting
)
from app.utils.seed_data import seed_database

class Phase2SeedingTestCase(unittest.TestCase):
    def setUp(self):
        """Set up in-memory SQLite database for testing seed operations."""
        self.app = create_app('testing')
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        """Clean up in-memory database."""
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_seed_creates_all_entities(self):
        """Verify seeding creates users, academic structure, and attendance records."""
        result = seed_database(verbose=False)
        self.assertEqual(result['status'], 'success')

        # Check entity counts
        self.assertGreaterEqual(User.query.count(), 20)
        self.assertEqual(Department.query.count(), 2)
        self.assertEqual(Class.query.count(), 2)
        self.assertEqual(Subject.query.count(), 5)
        self.assertEqual(FacultyProfile.query.count(), 3)
        self.assertEqual(StudentProfile.query.count(), 18)
        self.assertEqual(FacultyAssignment.query.count(), 5)
        self.assertGreaterEqual(AttendanceSession.query.count(), 20)
        self.assertGreaterEqual(AttendanceRecord.query.count(), 200)

        # Check system setting
        threshold = SystemSetting.get_int('min_attendance_threshold')
        self.assertEqual(threshold, 75)

    def test_seed_idempotency(self):
        """Verify running seed_database twice does not create duplicate entries or crash."""
        # First run
        res1 = seed_database(verbose=False)
        users_count_1 = User.query.count()
        sessions_count_1 = AttendanceSession.query.count()
        records_count_1 = AttendanceRecord.query.count()

        # Second run
        res2 = seed_database(verbose=False)
        users_count_2 = User.query.count()
        sessions_count_2 = AttendanceSession.query.count()
        records_count_2 = AttendanceRecord.query.count()

        self.assertEqual(users_count_1, users_count_2)
        self.assertEqual(sessions_count_1, sessions_count_2)
        self.assertEqual(records_count_1, records_count_2)
        self.assertEqual(res2['sessions_added'], 0)
        self.assertEqual(res2['records_added'], 0)

    def test_seeded_user_passwords_are_hashed(self):
        """Verify all seeded users have hashed passwords and verify with check_password."""
        seed_database(verbose=False)
        all_users = User.query.all()
        for u in all_users:
            # Hash must not be plain text
            self.assertNotEqual(u.password_hash, 'admin123')
            self.assertNotEqual(u.password_hash, 'faculty123')
            self.assertNotEqual(u.password_hash, 'student123')
            self.assertTrue(u.password_hash.startswith(('scrypt:', 'pbkdf2:')))

        # Verify known login credentials
        admin = User.query.filter_by(username='admin').first()
        self.assertIsNotNone(admin)
        self.assertTrue(admin.check_password('admin123'))

        faculty = User.query.filter_by(username='fac_sharma').first()
        self.assertIsNotNone(faculty)
        self.assertTrue(faculty.check_password('faculty123'))

        student = User.query.filter_by(username='student_aarav').first()
        self.assertIsNotNone(student)
        self.assertTrue(student.check_password('student123'))

    def test_seeded_defaulters_identified(self):
        """Verify targeted students have attendance below 75% and eligible students are above."""
        seed_database(verbose=False)

        # Aarav Patel should be eligible
        s_aarav = StudentProfile.query.filter_by(roll_number='2026CSE001').first()
        self.assertIsNotNone(s_aarav)
        aarav_summary = s_aarav.get_attendance_summary()
        self.assertGreaterEqual(aarav_summary['percentage'], 75.0)
        self.assertEqual(aarav_summary['status'], 'Eligible')

        # Vikram Singh was specifically designated as a low attendance defaulter
        s_vikram = StudentProfile.query.filter_by(roll_number='2026CSE005').first()
        self.assertIsNotNone(s_vikram)
        vikram_summary = s_vikram.get_attendance_summary()
        self.assertLess(vikram_summary['percentage'], 75.0)
        self.assertEqual(vikram_summary['status'], 'Shortage')

if __name__ == '__main__':
    unittest.main()
