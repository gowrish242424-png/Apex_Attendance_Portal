"""Database Seeding Engine for Advanced Attendance Management System (COP Project).

Creates realistic, idempotent demo data for:
- System settings (threshold, college name, academic session)
- Administrator account
- Departments, Classes, and Subjects
- Faculty accounts & profiles
- Student accounts & profiles
- Faculty-Subject-Class assignments
- Historical Attendance Sessions & Student Attendance Records
"""

from datetime import date, timedelta
from app.extensions import db
from app.models.settings import SystemSetting
from app.models.academic import Department, Class, Subject, FacultyAssignment
from app.models.user import User, FacultyProfile, StudentProfile
from app.models.attendance import AttendanceSession, AttendanceRecord

def seed_system_settings():
    """Seed or update global system settings."""
    settings = [
        ('min_attendance_threshold', '75', 'Minimum required attendance percentage for exam eligibility'),
        ('college_name', 'Apex Institute of Technology', 'Official institutional name'),
        ('academic_year', '2026-2027', 'Current active academic year'),
        ('current_semester', '5', 'Current active semester'),
    ]
    count = 0
    for key, val, desc in settings:
        s = SystemSetting.query.filter_by(setting_key=key).first()
        if not s:
            s = SystemSetting(setting_key=key, setting_value=val, description=desc)
            db.session.add(s)
            count += 1
    db.session.commit()
    return count


def seed_admin_user():
    """Seed the primary administrator account."""
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            email='admin@apex.edu',
            role='admin',
            is_active=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        return admin, True
    return admin, False


def seed_departments():
    """Seed academic departments."""
    depts_data = [
        ('CSE', 'Computer Science & Engineering', 'Department of Computer Science and Engineering'),
        ('ECE', 'Electronics & Communication Engineering', 'Department of Electronics and Communication Engineering'),
    ]
    created = {}
    for code, name, desc in depts_data:
        dept = Department.query.filter_by(code=code).first()
        if not dept:
            dept = Department(code=code, name=name, description=desc)
            db.session.add(dept)
            db.session.flush()
        created[code] = dept
    db.session.commit()
    return created


def seed_classes(depts):
    """Seed classes/cohorts."""
    classes_data = [
        ('CSE-3A', depts['CSE'].id, 5, '2026-2027'),
        ('ECE-3A', depts['ECE'].id, 5, '2026-2027'),
    ]
    created = {}
    for name, dept_id, sem, year in classes_data:
        cls_obj = Class.query.filter_by(name=name, department_id=dept_id, academic_year=year).first()
        if not cls_obj:
            cls_obj = Class(name=name, department_id=dept_id, semester=sem, academic_year=year)
            db.session.add(cls_obj)
            db.session.flush()
        created[name] = cls_obj
    db.session.commit()
    return created


def seed_subjects(depts):
    """Seed academic courses/subjects."""
    subjects_data = [
        ('CS501', 'Database Management Systems', depts['CSE'].id, 5, 4),
        ('CS502', 'Operating Systems', depts['CSE'].id, 5, 4),
        ('CS503', 'Computer Networks', depts['CSE'].id, 5, 3),
        ('EC501', 'Microprocessors & Microcontrollers', depts['ECE'].id, 5, 4),
        ('EC502', 'Digital Signal Processing', depts['ECE'].id, 5, 3),
    ]
    created = {}
    for code, name, dept_id, sem, credits in subjects_data:
        sub = Subject.query.filter_by(code=code).first()
        if not sub:
            sub = Subject(code=code, name=name, department_id=dept_id, semester=sem, credits=credits)
            db.session.add(sub)
            db.session.flush()
        created[code] = sub
    db.session.commit()
    return created


def seed_faculty(depts):
    """Seed faculty accounts and profiles."""
    faculty_data = [
        (
            'fac_sharma', 'sharma@apex.edu', 'faculty123',
            'EMP-CSE-101', 'Dr. Rajesh Sharma', depts['CSE'].id, 'Associate Professor', '9876543210'
        ),
        (
            'fac_gupta', 'gupta@apex.edu', 'faculty123',
            'EMP-CSE-102', 'Prof. Priya Gupta', depts['CSE'].id, 'Assistant Professor', '9876543211'
        ),
        (
            'fac_verma', 'verma@apex.edu', 'faculty123',
            'EMP-ECE-201', 'Dr. Amit Verma', depts['ECE'].id, 'Professor & HOD', '9876543212'
        ),
    ]
    created = {}
    for uname, email, pwd, emp_id, full_name, dept_id, desig, phone in faculty_data:
        user = User.query.filter_by(username=uname).first()
        if not user:
            user = User(username=uname, email=email, role='faculty', is_active=True)
            user.set_password(pwd)
            db.session.add(user)
            db.session.flush()

        profile = FacultyProfile.query.filter_by(user_id=user.id).first()
        if not profile:
            profile = FacultyProfile(
                user_id=user.id,
                employee_id=emp_id,
                full_name=full_name,
                department_id=dept_id,
                designation=desig,
                phone=phone
            )
            db.session.add(profile)
            db.session.flush()
        created[uname] = profile
    db.session.commit()
    return created


def seed_faculty_assignments(faculty, classes, subjects):
    """Assign faculty members to subjects for specific classes."""
    assignments = [
        (faculty['fac_sharma'].id, classes['CSE-3A'].id, subjects['CS501'].id, '2026-2027'),
        (faculty['fac_gupta'].id, classes['CSE-3A'].id, subjects['CS502'].id, '2026-2027'),
        (faculty['fac_sharma'].id, classes['CSE-3A'].id, subjects['CS503'].id, '2026-2027'),
        (faculty['fac_verma'].id, classes['ECE-3A'].id, subjects['EC501'].id, '2026-2027'),
        (faculty['fac_verma'].id, classes['ECE-3A'].id, subjects['EC502'].id, '2026-2027'),
    ]
    count = 0
    for fid, cid, sid, year in assignments:
        assign = FacultyAssignment.query.filter_by(
            faculty_id=fid, class_id=cid, subject_id=sid, academic_year=year
        ).first()
        if not assign:
            assign = FacultyAssignment(
                faculty_id=fid, class_id=cid, subject_id=sid, academic_year=year
            )
            db.session.add(assign)
            count += 1
    db.session.commit()
    return count


def seed_students(depts, classes):
    """Seed student accounts and profiles."""
    students_data = [
        # CSE-3A Students
        ('student_aarav', 'aarav@apex.edu', '2026CSE001', 'Aarav Patel', classes['CSE-3A'].id, depts['CSE'].id, 5, '9811000001'),
        ('student_ananya', 'ananya@apex.edu', '2026CSE002', 'Ananya Iyer', classes['CSE-3A'].id, depts['CSE'].id, 5, '9811000002'),
        ('student_rohan', 'rohan@apex.edu', '2026CSE003', 'Rohan Desai', classes['CSE-3A'].id, depts['CSE'].id, 5, '9811000003'),
        ('student_sneha', 'sneha@apex.edu', '2026CSE004', 'Sneha Kulkarni', classes['CSE-3A'].id, depts['CSE'].id, 5, '9811000004'),
        ('student_vikram', 'vikram@apex.edu', '2026CSE005', 'Vikram Singh', classes['CSE-3A'].id, depts['CSE'].id, 5, '9811000005'),  # Target: Defaulter (<70%)
        ('student_diya', 'diya@apex.edu', '2026CSE006', 'Diya Nair', classes['CSE-3A'].id, depts['CSE'].id, 5, '9811000006'),
        ('student_kabir', 'kabir@apex.edu', '2026CSE007', 'Kabir Mehta', classes['CSE-3A'].id, depts['CSE'].id, 5, '9811000007'),    # Target: Defaulter (<70%)
        ('student_riya', 'riya@apex.edu', '2026CSE008', 'Riya Sen', classes['CSE-3A'].id, depts['CSE'].id, 5, '9811000008'),
        ('student_arjun', 'arjun@apex.edu', '2026CSE009', 'Arjun Reddy', classes['CSE-3A'].id, depts['CSE'].id, 5, '9811000009'),
        ('student_tanvi', 'tanvi@apex.edu', '2026CSE010', 'Tanvi Joshi', classes['CSE-3A'].id, depts['CSE'].id, 5, '9811000010'),
        ('student_aditya', 'aditya@apex.edu', '2026CSE011', 'Aditya Rao', classes['CSE-3A'].id, depts['CSE'].id, 5, '9811000011'),
        ('student_ishita', 'ishita@apex.edu', '2026CSE012', 'Ishita Roy', classes['CSE-3A'].id, depts['CSE'].id, 5, '9811000012'),

        # ECE-3A Students
        ('student_siddharth', 'siddharth@apex.edu', '2026ECE001', 'Siddharth Rao', classes['ECE-3A'].id, depts['ECE'].id, 5, '9822000001'),
        ('student_pooja', 'pooja@apex.edu', '2026ECE002', 'Pooja Hegde', classes['ECE-3A'].id, depts['ECE'].id, 5, '9822000002'),
        ('student_nikhil', 'nikhil@apex.edu', '2026ECE003', 'Nikhil Bhat', classes['ECE-3A'].id, depts['ECE'].id, 5, '9822000003'),
        ('student_meera', 'meera@apex.edu', '2026ECE004', 'Meera Nambiar', classes['ECE-3A'].id, depts['ECE'].id, 5, '9822000004'),
        ('student_rahul', 'rahul@apex.edu', '2026ECE005', 'Rahul Ghosh', classes['ECE-3A'].id, depts['ECE'].id, 5, '9822000005'),  # Target: Defaulter (<70%)
        ('student_kavya', 'kavya@apex.edu', '2026ECE006', 'Kavya Pillai', classes['ECE-3A'].id, depts['ECE'].id, 5, '9822000006'),
    ]
    created = {}
    for uname, email, roll, full_name, cid, dept_id, sem, phone in students_data:
        user = User.query.filter_by(username=uname).first()
        if not user:
            user = User(username=uname, email=email, role='student', is_active=True)
            user.set_password('student123')
            db.session.add(user)
            db.session.flush()

        profile = StudentProfile.query.filter_by(user_id=user.id).first()
        if not profile:
            profile = StudentProfile(
                user_id=user.id,
                roll_number=roll,
                full_name=full_name,
                class_id=cid,
                department_id=dept_id,
                semester=sem,
                phone=phone
            )
            db.session.add(profile)
            db.session.flush()
        created[roll] = profile
    db.session.commit()
    return created


def seed_attendance_history(faculty, classes, subjects, students):
    """Seed historical attendance sessions and student records."""
    # Defaulter roll numbers intentionally kept with low attendance
    defaulter_rolls = {'2026CSE005', '2026CSE007', '2026ECE005'}

    # Generate dates for past 10 instructional days (excluding weekends)
    base_date = date.today() - timedelta(days=16)
    instructional_dates = []
    curr = base_date
    while len(instructional_dates) < 10:
        if curr.weekday() < 5:  # Monday to Friday
            instructional_dates.append(curr)
        curr += timedelta(days=1)

    # Class CSE-3A roster
    cse_students = [s for s in students.values() if s.class_id == classes['CSE-3A'].id]
    ece_students = [s for s in students.values() if s.class_id == classes['ECE-3A'].id]

    # Session plans
    session_plans = [
        # (Class, Subject, Faculty, Dates, Slot)
        (classes['CSE-3A'].id, subjects['CS501'].id, faculty['fac_sharma'].id, instructional_dates[:10], 'Period 1', cse_students),
        (classes['CSE-3A'].id, subjects['CS502'].id, faculty['fac_gupta'].id, instructional_dates[:8], 'Period 2', cse_students),
        (classes['CSE-3A'].id, subjects['CS503'].id, faculty['fac_sharma'].id, instructional_dates[:6], 'Period 3', cse_students),
        (classes['ECE-3A'].id, subjects['EC501'].id, faculty['fac_verma'].id, instructional_dates[:8], 'Period 1', ece_students),
        (classes['ECE-3A'].id, subjects['EC502'].id, faculty['fac_verma'].id, instructional_dates[:6], 'Period 2', ece_students),
    ]

    total_sessions_created = 0
    total_records_created = 0

    for cid, sid, fid, dates, slot, roster in session_plans:
        for idx, sdate in enumerate(dates):
            # Check or create session
            session = AttendanceSession.query.filter_by(
                class_id=cid, subject_id=sid, session_date=sdate, session_slot=slot
            ).first()
            if not session:
                session = AttendanceSession(
                    class_id=cid,
                    subject_id=sid,
                    faculty_id=fid,
                    session_date=sdate,
                    session_slot=slot
                )
                db.session.add(session)
                db.session.flush()
                total_sessions_created += 1

            # Create attendance records for each student in the class
            for stud in roster:
                rec = AttendanceRecord.query.filter_by(
                    session_id=session.id, student_id=stud.id
                ).first()
                if not rec:
                    # Determine status
                    if stud.roll_number in defaulter_rolls:
                        # Defaulters attend ~50-60% of sessions
                        status = 'PRESENT' if (idx % 2 == 0) else 'ABSENT'
                    else:
                        # Normal students attend ~85-95%
                        status = 'ABSENT' if (idx == 3 and stud.id % 2 == 0) else 'PRESENT'

                    rec = AttendanceRecord(
                        session_id=session.id,
                        student_id=stud.id,
                        status=status,
                        remarks='Medical Leave' if status == 'ABSENT' and idx == 3 else None
                    )
                    db.session.add(rec)
                    total_records_created += 1

    db.session.commit()
    return total_sessions_created, total_records_created


def seed_database(verbose=False):
    """Main entry point to safely seed the entire database idempotently."""
    if verbose:
        print("[*] Seeding System Settings...")
    seed_system_settings()

    if verbose:
        print("[*] Seeding Administrator Account...")
    seed_admin_user()

    if verbose:
        print("[*] Seeding Departments...")
    depts = seed_departments()

    if verbose:
        print("[*] Seeding Classes...")
    classes = seed_classes(depts)

    if verbose:
        print("[*] Seeding Subjects...")
    subjects = seed_subjects(depts)

    if verbose:
        print("[*] Seeding Faculty Members...")
    faculty = seed_faculty(depts)

    if verbose:
        print("[*] Seeding Faculty Course Allocations...")
    seed_faculty_assignments(faculty, classes, subjects)

    if verbose:
        print("[*] Seeding Students...")
    students = seed_students(depts, classes)

    if verbose:
        print("[*] Seeding Attendance Sessions and Records...")
    sess_count, rec_count = seed_attendance_history(faculty, classes, subjects, students)

    if verbose:
        print(f"[+] Seeding complete! Added {sess_count} sessions and {rec_count} records.")

    return {
        'status': 'success',
        'departments': len(depts),
        'classes': len(classes),
        'subjects': len(subjects),
        'faculty': len(faculty),
        'students': len(students),
        'sessions_added': sess_count,
        'records_added': rec_count
    }


if __name__ == '__main__':
    from app import create_app
    app = create_app('development')
    with app.app_context():
        seed_database(verbose=True)
