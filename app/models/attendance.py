from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint, CheckConstraint
from app.extensions import db

class AttendanceSession(db.Model):
    """An individual classroom attendance event conducted by a faculty member."""
    __tablename__ = 'attendance_sessions'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
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
    faculty_id = db.Column(
        db.Integer,
        db.ForeignKey('faculty_profiles.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    session_date = db.Column(db.Date, nullable=False, index=True)
    session_slot = db.Column(db.String(20), default='Period 1', nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            'class_id', 'subject_id', 'session_date', 'session_slot',
            name='uq_session_class_sub_date_slot'
        ),
    )

    # Relationships
    class_group = db.relationship('Class', back_populates='attendance_sessions')
    subject = db.relationship('Subject', back_populates='attendance_sessions')
    faculty = db.relationship('FacultyProfile', back_populates='conducted_sessions')
    records = db.relationship(
        'AttendanceRecord',
        back_populates='session',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f"<AttendanceSession ID={self.id} Class={self.class_id} Subject={self.subject_id} Date={self.session_date} Slot={self.session_slot}>"

    @property
    def total_students(self):
        return len(self.records)

    @property
    def present_count(self):
        return sum(1 for r in self.records if r.status == 'PRESENT')

    @property
    def absent_count(self):
        return sum(1 for r in self.records if r.status == 'ABSENT')

    @property
    def attendance_rate(self):
        if not self.records:
            return 0.0
        return round((self.present_count / len(self.records)) * 100, 2)


class AttendanceRecord(db.Model):
    """Individual student attendance mark (Present / Absent) for a specific session."""
    __tablename__ = 'attendance_records'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey('attendance_sessions.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    student_id = db.Column(
        db.Integer,
        db.ForeignKey('student_profiles.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    status = db.Column(db.String(10), nullable=False)
    remarks = db.Column(db.String(150), nullable=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint('session_id', 'student_id', name='uq_record_session_student'),
        CheckConstraint("status IN ('PRESENT', 'ABSENT')", name='chk_attendance_status'),
    )

    # Relationships
    session = db.relationship('AttendanceSession', back_populates='records')
    student = db.relationship('StudentProfile', back_populates='attendance_records')

    def __repr__(self):
        return f"<AttendanceRecord Session={self.session_id} Student={self.student_id} Status={self.status}>"

    @property
    def is_present(self):
        return self.status == 'PRESENT'

    @property
    def is_absent(self):
        return self.status == 'ABSENT'
