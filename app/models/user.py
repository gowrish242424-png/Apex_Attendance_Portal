from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db

class User(db.Model, UserMixin):
    """Core user account model supporting Admin, Faculty, and Student roles."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(60), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'faculty', 'student'
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # 1-to-1 relationships to profile models
    faculty_profile = db.relationship(
        'FacultyProfile',
        back_populates='user',
        uselist=False,
        cascade='all, delete-orphan'
    )
    student_profile = db.relationship(
        'StudentProfile',
        back_populates='user',
        uselist=False,
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"

    def set_password(self, password):
        """Hash and store the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify the password against stored hash."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_faculty(self):
        return self.role == 'faculty'

    @property
    def is_student(self):
        return self.role == 'student'

    @property
    def display_name(self):
        if self.is_faculty and self.faculty_profile:
            return self.faculty_profile.full_name
        if self.is_student and self.student_profile:
            return self.student_profile.full_name
        return self.username


class FacultyProfile(db.Model):
    """Institutional profile for Faculty members."""
    __tablename__ = 'faculty_profiles'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        unique=True,
        nullable=False,
        index=True
    )
    employee_id = db.Column(db.String(30), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(100), nullable=False)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey('departments.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    designation = db.Column(db.String(60), nullable=False, default='Assistant Professor')
    phone = db.Column(db.String(20), nullable=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    user = db.relationship('User', back_populates='faculty_profile')
    department = db.relationship('Department', back_populates='faculty_members')
    assignments = db.relationship(
        'FacultyAssignment',
        back_populates='faculty',
        cascade='all, delete-orphan'
    )
    conducted_sessions = db.relationship(
        'AttendanceSession',
        back_populates='faculty'
    )

    def __repr__(self):
        return f"<FacultyProfile {self.employee_id}: {self.full_name}>"


class StudentProfile(db.Model):
    """Institutional profile for enrolled Students."""
    __tablename__ = 'student_profiles'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        unique=True,
        nullable=False,
        index=True
    )
    roll_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(100), nullable=False)
    class_id = db.Column(
        db.Integer,
        db.ForeignKey('classes.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    department_id = db.Column(
        db.Integer,
        db.ForeignKey('departments.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    semester = db.Column(db.Integer, nullable=False, default=1)
    phone = db.Column(db.String(20), nullable=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    user = db.relationship('User', back_populates='student_profile')
    enrolled_class = db.relationship('Class', back_populates='students')
    department = db.relationship('Department', back_populates='students')
    attendance_records = db.relationship(
        'AttendanceRecord',
        back_populates='student',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f"<StudentProfile {self.roll_number}: {self.full_name}>"

    def get_attendance_summary(self):
        """Calculate overall attendance percentage across all subjects."""
        total_sessions = len(self.attendance_records)
        if total_sessions == 0:
            return {
                'total': 0,
                'attended': 0,
                'absent': 0,
                'percentage': None,
                'status': 'Not Started'
            }

        attended = sum(1 for rec in self.attendance_records if rec.status == 'PRESENT')
        absent = total_sessions - attended
        percentage = round((attended / total_sessions) * 100, 2)

        return {
            'total': total_sessions,
            'attended': attended,
            'absent': absent,
            'percentage': percentage,
            'status': 'Eligible' if percentage >= 75.0 else 'Shortage'
        }

    def get_subject_attendance(self, subject_id):
        """Calculate attendance summary for a specific subject."""
        records = [
            rec for rec in self.attendance_records
            if rec.session and rec.session.subject_id == subject_id
        ]
        total = len(records)
        if total == 0:
            return {
                'total': 0,
                'attended': 0,
                'absent': 0,
                'percentage': None,
                'status': 'Not Started'
            }

        attended = sum(1 for rec in records if rec.status == 'PRESENT')
        absent = total - attended
        percentage = round((attended / total) * 100, 2)

        return {
            'total': total,
            'attended': attended,
            'absent': absent,
            'percentage': percentage,
            'status': 'Eligible' if percentage >= 75.0 else 'Shortage'
        }
