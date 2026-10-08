from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint
from app.extensions import db

class Department(db.Model):
    """Academic Department (e.g., Computer Science, Electrical Engineering)."""
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(10), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    classes = db.relationship('Class', back_populates='department', cascade='all, delete-orphan')
    subjects = db.relationship('Subject', back_populates='department', cascade='all, delete-orphan')
    faculty_members = db.relationship('FacultyProfile', back_populates='department')
    students = db.relationship('StudentProfile', back_populates='department')

    def __repr__(self):
        return f"<Department {self.code}: {self.name}>"

    @property
    def total_classes(self):
        return len(self.classes)

    @property
    def total_students(self):
        return len(self.students)

    @property
    def total_faculty(self):
        return len(self.faculty_members)


class Class(db.Model):
    """Academic Class / Cohort / Section (e.g., CSE-3A, Semester 5)."""
    __tablename__ = 'classes'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), nullable=False)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey('departments.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    semester = db.Column(db.Integer, nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint('name', 'department_id', 'academic_year', name='uq_class_name_dept_year'),
    )

    # Relationships
    department = db.relationship('Department', back_populates='classes')
    students = db.relationship('StudentProfile', back_populates='enrolled_class')
    faculty_assignments = db.relationship('FacultyAssignment', back_populates='class_group', cascade='all, delete-orphan')
    attendance_sessions = db.relationship('AttendanceSession', back_populates='class_group', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Class {self.name} (Sem {self.semester}, {self.academic_year})>"

    @property
    def student_count(self):
        return len(self.students)


class Subject(db.Model):
    """Curriculum Subject / Course (e.g., CS501 Database Systems)."""
    __tablename__ = 'subjects'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey('departments.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    semester = db.Column(db.Integer, nullable=False)
    credits = db.Column(db.Integer, default=3, nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    department = db.relationship('Department', back_populates='subjects')
    faculty_assignments = db.relationship('FacultyAssignment', back_populates='subject', cascade='all, delete-orphan')
    attendance_sessions = db.relationship('AttendanceSession', back_populates='subject', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Subject {self.code}: {self.name}>"


class FacultyAssignment(db.Model):
    """Association linking Faculty to a Subject for a specific Class and Academic Year."""
    __tablename__ = 'faculty_assignments'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    faculty_id = db.Column(
        db.Integer,
        db.ForeignKey('faculty_profiles.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    class_id = db.Column(
        db.Integer,
        db.ForeignKey('classes.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    subject_id = db.Column(
        db.Integer,
        db.ForeignKey('subjects.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    academic_year = db.Column(db.String(20), nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint('faculty_id', 'class_id', 'subject_id', 'academic_year', name='uq_faculty_assignment'),
    )

    # Relationships
    faculty = db.relationship('FacultyProfile', back_populates='assignments')
    class_group = db.relationship('Class', back_populates='faculty_assignments')
    subject = db.relationship('Subject', back_populates='faculty_assignments')

    def __repr__(self):
        return f"<FacultyAssignment Faculty={self.faculty_id} Class={self.class_id} Subject={self.subject_id}>"
