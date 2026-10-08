from app.models.user import User, FacultyProfile, StudentProfile
from app.models.academic import Department, Class, Subject, FacultyAssignment
from app.models.attendance import AttendanceSession, AttendanceRecord
from app.models.settings import SystemSetting

__all__ = [
    'User',
    'FacultyProfile',
    'StudentProfile',
    'Department',
    'Class',
    'Subject',
    'FacultyAssignment',
    'AttendanceSession',
    'AttendanceRecord',
    'SystemSetting',
]
