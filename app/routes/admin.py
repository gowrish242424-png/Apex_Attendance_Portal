from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from app.extensions import db
from app.utils.decorators import admin_required
from app.models.academic import Department, Class, Subject, FacultyAssignment
from app.models.user import User, StudentProfile, FacultyProfile
from app.models.attendance import AttendanceSession, AttendanceRecord
from app.models.settings import SystemSetting
from app.services.report_service import ReportService
from app.utils.validators import (
    validate_string, validate_id, validate_date,
    validate_date_range, validate_threshold,
    validate_email, validate_phone, validate_semester, validate_credits
)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# =====================================================================
# 1. ADMIN DASHBOARD
# =====================================================================

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    """Main administrative dashboard with metrics and governance shortcuts."""
    stats = {
        'total_departments': Department.query.count(),
        'total_classes': Class.query.count(),
        'total_subjects': Subject.query.count(),
        'total_faculty': FacultyProfile.query.count(),
        'total_students': StudentProfile.query.count(),
        'total_allocations': FacultyAssignment.query.count(),
        'total_sessions': AttendanceSession.query.count(),
        'threshold': SystemSetting.get_int('min_attendance_threshold', 75),
        'college_name': SystemSetting.get_value('college_name', 'Apex Institute of Technology'),
        'academic_year': SystemSetting.get_value('academic_year', '2026-2027')
    }

    # Fetch recent departments and classes for quick reference
    recent_classes = Class.query.order_by(Class.id.desc()).limit(5).all()
    recent_allocations = FacultyAssignment.query.order_by(FacultyAssignment.id.desc()).limit(5).all()

    return render_template(
        'admin/dashboard.html',
        user=current_user,
        stats=stats,
        recent_classes=recent_classes,
        recent_allocations=recent_allocations
    )


# =====================================================================
# 2. DEPARTMENT MANAGEMENT
# =====================================================================

@admin_bp.route('/departments')
@admin_required
def departments():
    """List all departments."""
    search = request.args.get('search', '').strip()
    query = Department.query
    if search:
        query = query.filter(
            (Department.name.ilike(f"%{search}%")) |
            (Department.code.ilike(f"%{search}%"))
        )
    depts_list = query.order_by(Department.code.asc()).all()
    return render_template('admin/departments.html', departments=depts_list, search=search)


@admin_bp.route('/departments/create', methods=['POST'])
@admin_required
def create_department():
    """Add a new academic department."""
    code = request.form.get('code', '').strip().upper()
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()

    if not code or not name:
        flash("Department code and name are required.", "danger")
        return redirect(url_for('admin.departments'))

    # Check for duplicate code
    existing = Department.query.filter_by(code=code).first()
    if existing:
        flash(f"Department code '{code}' already exists. Please choose a unique code.", "danger")
        return redirect(url_for('admin.departments'))

    dept = Department(code=code, name=name, description=description or None)
    db.session.add(dept)
    db.session.commit()
    flash(f"Department '{code} - {name}' created successfully.", "success")
    return redirect(url_for('admin.departments'))


@admin_bp.route('/departments/<int:id>/edit', methods=['POST'])
@admin_required
def edit_department(id):
    """Edit department details."""
    dept = db.session.get(Department, id)
    if not dept:
        flash("Department not found.", "danger")
        return redirect(url_for('admin.departments'))

    code = request.form.get('code', '').strip().upper()
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()

    if not code or not name:
        flash("Department code and name are required.", "danger")
        return redirect(url_for('admin.departments'))

    # Check code conflict with other departments
    conflict = Department.query.filter(Department.code == code, Department.id != id).first()
    if conflict:
        flash(f"Department code '{code}' is already used by another department.", "danger")
        return redirect(url_for('admin.departments'))

    dept.code = code
    dept.name = name
    dept.description = description or None
    db.session.commit()
    flash(f"Department '{dept.code}' updated successfully.", "success")
    return redirect(url_for('admin.departments'))


@admin_bp.route('/departments/<int:id>/delete', methods=['POST'])
@admin_required
def delete_department(id):
    """Safely delete a department with referential integrity checks."""
    dept = db.session.get(Department, id)
    if not dept:
        flash("Department not found.", "danger")
        return redirect(url_for('admin.departments'))

    # Referential integrity safety checks
    if dept.classes:
        flash(f"Cannot delete department '{dept.code}': It contains {len(dept.classes)} active classes. Remove or reassign classes first.", "danger")
        return redirect(url_for('admin.departments'))
    if dept.subjects:
        flash(f"Cannot delete department '{dept.code}': It contains {len(dept.subjects)} active subjects. Remove subjects first.", "danger")
        return redirect(url_for('admin.departments'))
    if dept.faculty_members:
        flash(f"Cannot delete department '{dept.code}': {len(dept.faculty_members)} faculty members are assigned to it.", "danger")
        return redirect(url_for('admin.departments'))
    if dept.students:
        flash(f"Cannot delete department '{dept.code}': {len(dept.students)} students are enrolled in it.", "danger")
        return redirect(url_for('admin.departments'))

    db.session.delete(dept)
    db.session.commit()
    flash(f"Department '{dept.code}' deleted successfully.", "success")
    return redirect(url_for('admin.departments'))


# =====================================================================
# 3. CLASS MANAGEMENT
# =====================================================================

@admin_bp.route('/classes')
@admin_required
def classes():
    """List all classes with department filtering."""
    dept_id = request.args.get('department_id', type=int)
    search = request.args.get('search', '').strip()

    query = Class.query
    if dept_id:
        query = query.filter_by(department_id=dept_id)
    if search:
        query = query.filter(Class.name.ilike(f"%{search}%"))

    classes_list = query.order_by(Class.name.asc()).all()
    all_depts = Department.query.order_by(Department.code.asc()).all()

    return render_template(
        'admin/classes.html',
        classes=classes_list,
        departments=all_depts,
        selected_dept=dept_id,
        search=search
    )


@admin_bp.route('/classes/create', methods=['POST'])
@admin_required
def create_class():
    """Add a new class / cohort."""
    name, n_err = validate_string(request.form.get('name'), "Class Name", min_len=1, max_len=64)
    dept_raw = request.form.get('department_id')
    department_id, d_err = validate_id(dept_raw, "Department")
    sem_raw = request.form.get('semester')
    semester, s_err = validate_semester(sem_raw) if sem_raw is not None else (None, "Semester is required.")
    academic_year, y_err = validate_string(request.form.get('academic_year'), "Academic Year", min_len=1, max_len=30)

    if not name or not dept_raw or not sem_raw or not academic_year:
        flash("All class fields (Name, Department, Semester, Academic Year) are required.", "danger")
        return redirect(url_for('admin.classes'))

    if s_err or d_err or n_err or y_err:
        flash(s_err or d_err or n_err or y_err, "danger")
        return redirect(url_for('admin.classes'))

    dept = db.session.get(Department, department_id)
    if not dept:
        flash("Selected department does not exist.", "danger")
        return redirect(url_for('admin.classes'))

    # Uniqueness constraint check (name, department_id, academic_year)
    existing = Class.query.filter_by(
        name=name, department_id=department_id, academic_year=academic_year
    ).first()
    if existing:
        flash(f"Class '{name}' already exists in {dept.code} for academic year {academic_year}.", "danger")
        return redirect(url_for('admin.classes'))

    new_class = Class(
        name=name,
        department_id=department_id,
        semester=semester,
        academic_year=academic_year
    )
    db.session.add(new_class)
    db.session.commit()
    flash(f"Class '{name}' created successfully.", "success")
    return redirect(url_for('admin.classes'))


@admin_bp.route('/classes/<int:id>/edit', methods=['POST'])
@admin_required
def edit_class(id):
    """Edit class details."""
    cls_obj = db.session.get(Class, id)
    if not cls_obj:
        flash("Class not found.", "danger")
        return redirect(url_for('admin.classes'))

    name, n_err = validate_string(request.form.get('name'), "Class Name", min_len=1, max_len=64)
    dept_raw = request.form.get('department_id')
    department_id, d_err = validate_id(dept_raw, "Department")
    sem_raw = request.form.get('semester')
    semester, s_err = validate_semester(sem_raw) if sem_raw is not None else (None, "Semester is required.")
    academic_year, y_err = validate_string(request.form.get('academic_year'), "Academic Year", min_len=1, max_len=30)

    if not name or not dept_raw or not sem_raw or not academic_year:
        flash("All class fields are required.", "danger")
        return redirect(url_for('admin.classes'))

    if s_err or d_err or n_err or y_err:
        flash(s_err or d_err or n_err or y_err, "danger")
        return redirect(url_for('admin.classes'))

    conflict = Class.query.filter(
        Class.name == name,
        Class.department_id == department_id,
        Class.academic_year == academic_year,
        Class.id != id
    ).first()
    if conflict:
        flash("Another class with identical name, department, and academic year already exists.", "danger")
        return redirect(url_for('admin.classes'))

    cls_obj.name = name
    cls_obj.department_id = department_id
    cls_obj.semester = semester
    cls_obj.academic_year = academic_year
    db.session.commit()
    flash(f"Class '{cls_obj.name}' updated successfully.", "success")
    return redirect(url_for('admin.classes'))


@admin_bp.route('/classes/<int:id>/delete', methods=['POST'])
@admin_required
def delete_class(id):
    """Safely delete a class if it has no students or attendance records."""
    cls_obj = db.session.get(Class, id)
    if not cls_obj:
        flash("Class not found.", "danger")
        return redirect(url_for('admin.classes'))

    if cls_obj.students:
        flash(f"Cannot delete class '{cls_obj.name}': It has {len(cls_obj.students)} enrolled students.", "danger")
        return redirect(url_for('admin.classes'))
    if cls_obj.attendance_sessions:
        flash(f"Cannot delete class '{cls_obj.name}': It has {len(cls_obj.attendance_sessions)} recorded attendance sessions.", "danger")
        return redirect(url_for('admin.classes'))

    db.session.delete(cls_obj)
    db.session.commit()
    flash(f"Class '{cls_obj.name}' deleted successfully.", "success")
    return redirect(url_for('admin.classes'))


# =====================================================================
# 4. SUBJECT MANAGEMENT
# =====================================================================

@admin_bp.route('/subjects')
@admin_required
def subjects():
    """List all subjects with department and semester filters."""
    dept_id = request.args.get('department_id', type=int)
    semester = request.args.get('semester', type=int)
    search = request.args.get('search', '').strip()

    query = Subject.query
    if dept_id:
        query = query.filter_by(department_id=dept_id)
    if semester:
        query = query.filter_by(semester=semester)
    if search:
        query = query.filter(
            (Subject.name.ilike(f"%{search}%")) |
            (Subject.code.ilike(f"%{search}%"))
        )

    subjects_list = query.order_by(Subject.code.asc()).all()
    all_depts = Department.query.order_by(Department.code.asc()).all()

    return render_template(
        'admin/subjects.html',
        subjects=subjects_list,
        departments=all_depts,
        selected_dept=dept_id,
        selected_semester=semester,
        search=search
    )


@admin_bp.route('/subjects/create', methods=['POST'])
@admin_required
def create_subject():
    """Add a new subject."""
    code, c_err = validate_string(request.form.get('code'), "Subject Code", min_len=1, max_len=20)
    name, n_err = validate_string(request.form.get('name'), "Subject Name", min_len=1, max_len=120)
    dept_raw = request.form.get('department_id')
    department_id, d_err = validate_id(dept_raw, "Department")
    sem_raw = request.form.get('semester')
    semester, s_err = validate_semester(sem_raw) if sem_raw is not None else (None, "Semester is required.")
    credits_raw = request.form.get('credits', 3)
    credits_val, cr_err = validate_credits(credits_raw)

    if not code or not name or not dept_raw or not sem_raw:
        flash("Subject code, name, department, and semester are required.", "danger")
        return redirect(url_for('admin.subjects'))

    if s_err or cr_err or c_err or n_err or d_err:
        flash(s_err or cr_err or c_err or n_err or d_err, "danger")
        return redirect(url_for('admin.subjects'))

    code = code.upper()
    existing = Subject.query.filter_by(code=code).first()
    if existing:
        flash(f"Subject code '{code}' already exists.", "danger")
        return redirect(url_for('admin.subjects'))

    new_sub = Subject(
        code=code,
        name=name,
        department_id=department_id,
        semester=semester,
        credits=credits_val or 3
    )
    db.session.add(new_sub)
    db.session.commit()
    flash(f"Subject '{code} - {name}' created successfully.", "success")
    return redirect(url_for('admin.subjects'))


@admin_bp.route('/subjects/<int:id>/edit', methods=['POST'])
@admin_required
def edit_subject(id):
    """Edit subject details."""
    sub = db.session.get(Subject, id)
    if not sub:
        flash("Subject not found.", "danger")
        return redirect(url_for('admin.subjects'))

    code, c_err = validate_string(request.form.get('code'), "Subject Code", min_len=1, max_len=20)
    name, n_err = validate_string(request.form.get('name'), "Subject Name", min_len=1, max_len=120)
    dept_raw = request.form.get('department_id')
    department_id, d_err = validate_id(dept_raw, "Department")
    sem_raw = request.form.get('semester')
    semester, s_err = validate_semester(sem_raw) if sem_raw is not None else (None, "Semester is required.")
    credits_raw = request.form.get('credits', 3)
    credits_val, cr_err = validate_credits(credits_raw)

    if not code or not name or not dept_raw or not sem_raw:
        flash("All subject fields are required.", "danger")
        return redirect(url_for('admin.subjects'))

    if s_err or cr_err or c_err or n_err or d_err:
        flash(s_err or cr_err or c_err or n_err or d_err, "danger")
        return redirect(url_for('admin.subjects'))

    code = code.upper()
    conflict = Subject.query.filter(Subject.code == code, Subject.id != id).first()
    if conflict:
        flash(f"Subject code '{code}' is already used by another subject.", "danger")
        return redirect(url_for('admin.subjects'))

    sub.code = code
    sub.name = name
    sub.department_id = department_id
    sub.semester = semester
    sub.credits = credits_val or 3
    db.session.commit()
    flash(f"Subject '{sub.code}' updated successfully.", "success")
    return redirect(url_for('admin.subjects'))


@admin_bp.route('/subjects/<int:id>/delete', methods=['POST'])
@admin_required
def delete_subject(id):
    """Safely delete a subject if no attendance or allocations are linked."""
    sub = db.session.get(Subject, id)
    if not sub:
        flash("Subject not found.", "danger")
        return redirect(url_for('admin.subjects'))

    if sub.attendance_sessions:
        flash(f"Cannot delete subject '{sub.code}': It has {len(sub.attendance_sessions)} recorded attendance sessions.", "danger")
        return redirect(url_for('admin.subjects'))
    if sub.faculty_assignments:
        flash(f"Cannot delete subject '{sub.code}': It has {len(sub.faculty_assignments)} active faculty assignments.", "danger")
        return redirect(url_for('admin.subjects'))

    db.session.delete(sub)
    db.session.commit()
    flash(f"Subject '{sub.code}' deleted successfully.", "success")
    return redirect(url_for('admin.subjects'))


# =====================================================================
# 5. FACULTY MANAGEMENT
# =====================================================================

@admin_bp.route('/faculty')
@admin_required
def faculty():
    """List all faculty members with search and department filter."""
    dept_id = request.args.get('department_id', type=int)
    search = request.args.get('search', '').strip()

    query = FacultyProfile.query.join(User)
    if dept_id:
        query = query.filter(FacultyProfile.department_id == dept_id)
    if search:
        query = query.filter(
            (FacultyProfile.full_name.ilike(f"%{search}%")) |
            (FacultyProfile.employee_id.ilike(f"%{search}%")) |
            (User.username.ilike(f"%{search}%")) |
            (User.email.ilike(f"%{search}%"))
        )

    faculty_list = query.order_by(FacultyProfile.full_name.asc()).all()
    all_depts = Department.query.order_by(Department.code.asc()).all()

    return render_template(
        'admin/faculty.html',
        faculty_members=faculty_list,
        departments=all_depts,
        selected_dept=dept_id,
        search=search
    )


@admin_bp.route('/faculty/create', methods=['POST'])
@admin_required
def create_faculty():
    """Create faculty user account and associated profile."""
    username, u_err = validate_string(request.form.get('username'), "Username", min_len=1, max_len=64)
    email_raw = request.form.get('email', '')
    email, e_err = validate_email(email_raw) if email_raw else (None, "Email is required.")
    password, p_err = validate_string(request.form.get('password'), "Password", min_len=1, max_len=128)
    full_name, n_err = validate_string(request.form.get('full_name'), "Full Name", min_len=1, max_len=120)
    employee_id, emp_err = validate_string(request.form.get('employee_id'), "Employee ID", min_len=1, max_len=32)
    dept_raw = request.form.get('department_id')
    department_id = int(dept_raw) if dept_raw and str(dept_raw).isdigit() else None
    designation = request.form.get('designation', '').strip() or 'Assistant Professor'
    phone, ph_err = validate_phone(request.form.get('phone'))

    if not username or not email_raw or not password or not full_name or not employee_id:
        flash("Username, email, password, full name, and Employee ID are required.", "danger")
        return redirect(url_for('admin.faculty'))

    if e_err:
        flash(e_err, "danger")
        return redirect(url_for('admin.faculty'))

    if ph_err:
        flash(ph_err, "danger")
        return redirect(url_for('admin.faculty'))

    employee_id = employee_id.upper()
    # Uniqueness checks
    if User.query.filter_by(username=username).first():
        flash(f"Username '{username}' is already taken.", "danger")
        return redirect(url_for('admin.faculty'))
    if User.query.filter_by(email=email).first():
        flash(f"Email '{email}' is already registered.", "danger")
        return redirect(url_for('admin.faculty'))
    if FacultyProfile.query.filter_by(employee_id=employee_id).first():
        flash(f"Employee ID '{employee_id}' already exists.", "danger")
        return redirect(url_for('admin.faculty'))

    # Create User
    user = User(username=username, email=email, role='faculty', is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()

    # Create Profile
    profile = FacultyProfile(
        user_id=user.id,
        employee_id=employee_id,
        full_name=full_name,
        department_id=department_id or None,
        designation=designation,
        phone=phone or None
    )
    db.session.add(profile)
    db.session.commit()

    flash(f"Faculty member '{full_name}' ({employee_id}) registered successfully.", "success")
    return redirect(url_for('admin.faculty'))


@admin_bp.route('/faculty/<int:id>/edit', methods=['POST'])
@admin_required
def edit_faculty(id):
    """Edit faculty profile and user credentials."""
    profile = db.session.get(FacultyProfile, id)
    if not profile:
        flash("Faculty member not found.", "danger")
        return redirect(url_for('admin.faculty'))

    user = profile.user
    full_name, n_err = validate_string(request.form.get('full_name'), "Full Name", min_len=1, max_len=120)
    email_raw = request.form.get('email', '')
    email, e_err = validate_email(email_raw) if email_raw else (None, "Email is required.")
    dept_raw = request.form.get('department_id')
    department_id = int(dept_raw) if dept_raw and str(dept_raw).isdigit() else None
    designation = request.form.get('designation', '').strip()
    phone, ph_err = validate_phone(request.form.get('phone'))
    new_password = request.form.get('new_password', '').strip()

    if not full_name or not email_raw:
        flash("Full name and email are required.", "danger")
        return redirect(url_for('admin.faculty'))

    if e_err:
        flash(e_err, "danger")
        return redirect(url_for('admin.faculty'))

    if ph_err:
        flash(ph_err, "danger")
        return redirect(url_for('admin.faculty'))

    # Check email conflict
    email_conflict = User.query.filter(User.email == email, User.id != user.id).first()
    if email_conflict:
        flash(f"Email '{email}' is used by another account.", "danger")
        return redirect(url_for('admin.faculty'))

    profile.full_name = full_name
    profile.department_id = department_id or None
    profile.designation = designation or 'Assistant Professor'
    profile.phone = phone or None

    user.email = email
    if new_password:
        user.set_password(new_password)

    db.session.commit()
    flash(f"Faculty member '{profile.full_name}' updated successfully.", "success")
    return redirect(url_for('admin.faculty'))


@admin_bp.route('/faculty/<int:id>/toggle-status', methods=['POST'])
@admin_required
def toggle_faculty_status(id):
    """Activate or deactivate a faculty user account."""
    profile = db.session.get(FacultyProfile, id)
    if not profile or not profile.user:
        flash("Faculty account not found.", "danger")
        return redirect(url_for('admin.faculty'))

    user = profile.user
    user.is_active = not user.is_active
    db.session.commit()

    state = "activated" if user.is_active else "deactivated"
    flash(f"Faculty account for '{profile.full_name}' has been {state}.", "info")
    return redirect(url_for('admin.faculty'))


@admin_bp.route('/faculty/<int:id>/delete', methods=['POST'])
@admin_required
def delete_faculty(id):
    """Delete a faculty member safely, preventing removal if attendance history exists."""
    profile = db.session.get(FacultyProfile, id)
    if not profile:
        flash("Faculty member not found.", "danger")
        return redirect(url_for('admin.faculty'))

    # Audit safety: cannot delete if faculty conducted attendance sessions
    if profile.conducted_sessions:
        flash(f"Cannot delete '{profile.full_name}': {len(profile.conducted_sessions)} attendance sessions are recorded by this instructor. Deactivate the account instead to disable access without corrupting audit history.", "warning")
        return redirect(url_for('admin.faculty'))

    name = profile.full_name
    user = profile.user
    db.session.delete(user)  # Cascades to profile and assignments
    db.session.commit()
    flash(f"Faculty member '{name}' deleted successfully.", "success")
    return redirect(url_for('admin.faculty'))


# =====================================================================
# 6. STUDENT MANAGEMENT
# =====================================================================

@admin_bp.route('/students')
@admin_required
def students():
    """List all students with class, department filters, and search."""
    dept_id = request.args.get('department_id', type=int)
    class_id = request.args.get('class_id', type=int)
    search = request.args.get('search', '').strip()

    query = StudentProfile.query.join(User)
    if dept_id:
        query = query.filter(StudentProfile.department_id == dept_id)
    if class_id:
        query = query.filter(StudentProfile.class_id == class_id)
    if search:
        query = query.filter(
            (StudentProfile.full_name.ilike(f"%{search}%")) |
            (StudentProfile.roll_number.ilike(f"%{search}%")) |
            (User.username.ilike(f"%{search}%")) |
            (User.email.ilike(f"%{search}%"))
        )

    students_list = query.order_by(StudentProfile.roll_number.asc()).all()
    all_depts = Department.query.order_by(Department.code.asc()).all()
    all_classes = Class.query.order_by(Class.name.asc()).all()

    return render_template(
        'admin/students.html',
        students=students_list,
        departments=all_depts,
        classes=all_classes,
        selected_dept=dept_id,
        selected_class=class_id,
        search=search
    )


@admin_bp.route('/students/create', methods=['POST'])
@admin_required
def create_student():
    """Create student user account and associated student profile."""
    username, u_err = validate_string(request.form.get('username'), "Username", min_len=1, max_len=64)
    email_raw = request.form.get('email', '')
    email, e_err = validate_email(email_raw) if email_raw else (None, "Email is required.")
    password, p_err = validate_string(request.form.get('password'), "Password", min_len=1, max_len=128)
    full_name, n_err = validate_string(request.form.get('full_name'), "Full Name", min_len=1, max_len=120)
    roll_number, r_err = validate_string(request.form.get('roll_number'), "Roll Number", min_len=1, max_len=32)
    cls_raw = request.form.get('class_id')
    class_id = int(cls_raw) if cls_raw and str(cls_raw).isdigit() else None
    dept_raw = request.form.get('department_id')
    department_id = int(dept_raw) if dept_raw and str(dept_raw).isdigit() else None
    sem_raw = request.form.get('semester', 1)
    semester, s_err = validate_semester(sem_raw) if sem_raw is not None else (1, None)
    phone, ph_err = validate_phone(request.form.get('phone'))

    if not username or not email_raw or not password or not full_name or not roll_number:
        flash("Username, email, password, full name, and Roll Number are required.", "danger")
        return redirect(url_for('admin.students'))

    if e_err:
        flash(e_err, "danger")
        return redirect(url_for('admin.students'))

    if s_err:
        flash(s_err, "danger")
        return redirect(url_for('admin.students'))

    if ph_err:
        flash(ph_err, "danger")
        return redirect(url_for('admin.students'))

    roll_number = roll_number.upper()
    # Uniqueness checks
    if User.query.filter_by(username=username).first():
        flash(f"Username '{username}' is already taken.", "danger")
        return redirect(url_for('admin.students'))
    if User.query.filter_by(email=email).first():
        flash(f"Email '{email}' is already registered.", "danger")
        return redirect(url_for('admin.students'))
    if StudentProfile.query.filter_by(roll_number=roll_number).first():
        flash(f"Roll Number '{roll_number}' already exists.", "danger")
        return redirect(url_for('admin.students'))

    # Derive department if class selected
    if class_id and not department_id:
        target_class = db.session.get(Class, class_id)
        if target_class:
            department_id = target_class.department_id

    user = User(username=username, email=email, role='student', is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()

    profile = StudentProfile(
        user_id=user.id,
        roll_number=roll_number,
        full_name=full_name,
        class_id=class_id or None,
        department_id=department_id or None,
        semester=semester or 1,
        phone=phone or None
    )
    db.session.add(profile)
    db.session.commit()

    flash(f"Student '{full_name}' ({roll_number}) enrolled successfully.", "success")
    return redirect(url_for('admin.students'))


@admin_bp.route('/students/<int:id>/edit', methods=['POST'])
@admin_required
def edit_student(id):
    """Edit student profile and credentials."""
    profile = db.session.get(StudentProfile, id)
    if not profile:
        flash("Student not found.", "danger")
        return redirect(url_for('admin.students'))

    user = profile.user
    full_name, n_err = validate_string(request.form.get('full_name'), "Full Name", min_len=1, max_len=120)
    email_raw = request.form.get('email', '')
    email, e_err = validate_email(email_raw) if email_raw else (None, "Email is required.")
    cls_raw = request.form.get('class_id')
    class_id = int(cls_raw) if cls_raw and str(cls_raw).isdigit() else None
    dept_raw = request.form.get('department_id')
    department_id = int(dept_raw) if dept_raw and str(dept_raw).isdigit() else None
    sem_raw = request.form.get('semester')
    semester = None
    if sem_raw:
        semester, s_err = validate_semester(sem_raw)
        if s_err:
            flash(s_err, "danger")
            return redirect(url_for('admin.students'))
    phone, ph_err = validate_phone(request.form.get('phone'))
    new_password = request.form.get('new_password', '').strip()

    if not full_name or not email_raw:
        flash("Full name and email are required.", "danger")
        return redirect(url_for('admin.students'))

    if e_err:
        flash(e_err, "danger")
        return redirect(url_for('admin.students'))

    if ph_err:
        flash(ph_err, "danger")
        return redirect(url_for('admin.students'))

    conflict = User.query.filter(User.email == email, User.id != user.id).first()
    if conflict:
        flash(f"Email '{email}' is already in use by another account.", "danger")
        return redirect(url_for('admin.students'))

    profile.full_name = full_name
    profile.class_id = class_id or None
    profile.department_id = department_id or None
    profile.semester = semester or profile.semester
    profile.phone = phone or None

    user.email = email
    if new_password:
        user.set_password(new_password)

    db.session.commit()
    flash(f"Student '{profile.full_name}' ({profile.roll_number}) updated successfully.", "success")
    return redirect(url_for('admin.students'))


@admin_bp.route('/students/<int:id>/toggle-status', methods=['POST'])
@admin_required
def toggle_student_status(id):
    """Activate or deactivate a student user account."""
    profile = db.session.get(StudentProfile, id)
    if not profile or not profile.user:
        flash("Student account not found.", "danger")
        return redirect(url_for('admin.students'))

    user = profile.user
    user.is_active = not user.is_active
    db.session.commit()

    state = "activated" if user.is_active else "deactivated"
    flash(f"Student account for '{profile.full_name}' has been {state}.", "info")
    return redirect(url_for('admin.students'))


@admin_bp.route('/students/<int:id>/delete', methods=['POST'])
@admin_required
def delete_student(id):
    """Delete a student safely, preventing removal if attendance history exists."""
    profile = db.session.get(StudentProfile, id)
    if not profile:
        flash("Student not found.", "danger")
        return redirect(url_for('admin.students'))

    # Audit safety: cannot delete if attendance records exist
    if profile.attendance_records:
        flash(f"Cannot delete '{profile.full_name}': {len(profile.attendance_records)} attendance marks exist for this student. Deactivate the account instead to disable access without corrupting class calculations.", "warning")
        return redirect(url_for('admin.students'))

    name = profile.full_name
    user = profile.user
    db.session.delete(user)
    db.session.commit()
    flash(f"Student '{name}' deleted successfully.", "success")
    return redirect(url_for('admin.students'))


# =====================================================================
# 7. FACULTY COURSE ALLOCATION (ASSIGNMENTS)
# =====================================================================

@admin_bp.route('/allocations')
@admin_required
def allocations():
    """List faculty course assignments with filtering."""
    faculty_id = request.args.get('faculty_id', type=int)
    class_id = request.args.get('class_id', type=int)
    academic_year = request.args.get('academic_year', '').strip()

    query = FacultyAssignment.query
    if faculty_id:
        query = query.filter_by(faculty_id=faculty_id)
    if class_id:
        query = query.filter_by(class_id=class_id)
    if academic_year:
        query = query.filter_by(academic_year=academic_year)

    allocations_list = query.order_by(FacultyAssignment.id.desc()).all()
    all_faculty = FacultyProfile.query.order_by(FacultyProfile.full_name.asc()).all()
    all_classes = Class.query.order_by(Class.name.asc()).all()
    all_subjects = Subject.query.order_by(Subject.code.asc()).all()

    return render_template(
        'admin/allocations.html',
        allocations=allocations_list,
        faculty_members=all_faculty,
        classes=all_classes,
        subjects=all_subjects,
        selected_faculty=faculty_id,
        selected_class=class_id,
        selected_year=academic_year
    )


@admin_bp.route('/allocations/create', methods=['POST'])
@admin_required
def create_allocation():
    """Assign a faculty member to teach a subject for a class."""
    faculty_id = request.args.get('faculty_id', type=int) or request.form.get('faculty_id', type=int)
    class_id = request.form.get('class_id', type=int)
    subject_id = request.form.get('subject_id', type=int)
    academic_year = request.form.get('academic_year', '').strip()

    if not faculty_id or not class_id or not subject_id or not academic_year:
        flash("Faculty, Class, Subject, and Academic Year are all required for course allocation.", "danger")
        return redirect(url_for('admin.allocations'))

    # Verify entities exist
    faculty = db.session.get(FacultyProfile, faculty_id)
    cls_obj = db.session.get(Class, class_id)
    sub = db.session.get(Subject, subject_id)

    if not faculty or not cls_obj or not sub:
        flash("One or more selected records (Faculty, Class, or Subject) do not exist.", "danger")
        return redirect(url_for('admin.allocations'))

    # Unique constraint check: (faculty_id, class_id, subject_id, academic_year)
    existing = FacultyAssignment.query.filter_by(
        faculty_id=faculty_id,
        class_id=class_id,
        subject_id=subject_id,
        academic_year=academic_year
    ).first()

    if existing:
        flash(f"Allocation already exists: {faculty.full_name} is already assigned to {sub.code} ({cls_obj.name}) for {academic_year}.", "warning")
        return redirect(url_for('admin.allocations'))

    assignment = FacultyAssignment(
        faculty_id=faculty_id,
        class_id=class_id,
        subject_id=subject_id,
        academic_year=academic_year
    )
    db.session.add(assignment)
    db.session.commit()

    flash(f"Successfully allocated {sub.code} ({cls_obj.name}) to {faculty.full_name}.", "success")
    return redirect(url_for('admin.allocations'))


@admin_bp.route('/allocations/<int:id>/edit', methods=['POST'])
@admin_required
def edit_allocation(id):
    """Edit an existing course allocation."""
    assignment = db.session.get(FacultyAssignment, id)
    if not assignment:
        flash("Course allocation not found.", "danger")
        return redirect(url_for('admin.allocations'))

    faculty_id = request.form.get('faculty_id', type=int)
    class_id = request.form.get('class_id', type=int)
    subject_id = request.form.get('subject_id', type=int)
    academic_year = request.form.get('academic_year', '').strip()

    if not faculty_id or not class_id or not subject_id or not academic_year:
        flash("All fields are required.", "danger")
        return redirect(url_for('admin.allocations'))

    # Check for conflict
    conflict = FacultyAssignment.query.filter(
        FacultyAssignment.faculty_id == faculty_id,
        FacultyAssignment.class_id == class_id,
        FacultyAssignment.subject_id == subject_id,
        FacultyAssignment.academic_year == academic_year,
        FacultyAssignment.id != id
    ).first()

    if conflict:
        flash("An identical course allocation already exists.", "danger")
        return redirect(url_for('admin.allocations'))

    assignment.faculty_id = faculty_id
    assignment.class_id = class_id
    assignment.subject_id = subject_id
    assignment.academic_year = academic_year
    db.session.commit()

    flash("Course allocation updated successfully.", "success")
    return redirect(url_for('admin.allocations'))


@admin_bp.route('/allocations/<int:id>/delete', methods=['POST'])
@admin_required
def delete_allocation(id):
    """Remove a course allocation."""
    assignment = db.session.get(FacultyAssignment, id)
    if not assignment:
        flash("Course allocation not found.", "danger")
        return redirect(url_for('admin.allocations'))

    db.session.delete(assignment)
    db.session.commit()
    flash("Course allocation removed successfully.", "success")
    return redirect(url_for('admin.allocations'))


# =====================================================================
# 8. INSTITUTIONAL ANALYTICS & REPORTS (PHASE 7)
# =====================================================================

@admin_bp.route('/analytics')
@admin_required
def analytics():
    """Institutional-level attendance analytics dashboard with charts and summaries."""
    analytics_data = ReportService.get_institutional_analytics()
    departments = Department.query.order_by(Department.code.asc()).all()
    classes = Class.query.order_by(Class.name.asc()).all()
    return render_template(
        'admin/analytics.html',
        analytics=analytics_data,
        departments=departments,
        classes=classes
    )


# --- Class Attendance Reports ---

@admin_bp.route('/reports/classes')
@admin_required
def class_reports():
    """Class-wise attendance report with optional student breakdown."""
    dept_id = request.args.get('department_id', type=int)
    class_id = request.args.get('class_id', type=int)
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    df, dt, d_err = validate_date_range(date_from, date_to)
    if d_err:
        flash(d_err, "warning")
        date_from = ""
        date_to = ""

    report = ReportService.get_class_attendance_report(dept_id, class_id, date_from, date_to)
    departments = Department.query.order_by(Department.code.asc()).all()
    classes = Class.query.order_by(Class.name.asc()).all()

    return render_template(
        'admin/reports/classes.html',
        report=report,
        departments=departments,
        classes=classes,
        selected_dept=dept_id,
        selected_class=class_id,
        date_from=date_from,
        date_to=date_to
    )


@admin_bp.route('/reports/classes/export.csv')
@admin_required
def export_class_reports_csv():
    """Export filtered class attendance report as formula-safe CSV."""
    dept_id = request.args.get('department_id', type=int)
    class_id = request.args.get('class_id', type=int)
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    df, dt, d_err = validate_date_range(date_from, date_to)
    if d_err:
        date_from = ""
        date_to = ""

    report = ReportService.get_class_attendance_report(dept_id, class_id, date_from, date_to)

    if class_id and report['student_details']:
        # Detailed student breakdown
        cls_obj = db.session.get(Class, class_id)
        cls_name = cls_obj.name if cls_obj else f"Class_{class_id}"
        headers = ["Roll Number", "Student Name", "Class", "Attended", "Absent", "Total Sessions", "Turnout %", "Status"]
        rows = [
            [
                item['student'].roll_number,
                item['student'].full_name,
                item['class'].name,
                item['present'],
                item['absent'],
                item['total'],
                item['percentage'],
                item['status']
            ]
            for item in report['student_details']
        ]
        filename = f"class_{cls_name}_attendance_report.csv"
    else:
        # Aggregated class summaries
        headers = ["Class Name", "Department", "Semester", "Academic Year", "Students Enrolled", "Sessions Conducted", "Present Marks", "Absent Marks", "Turnout %"]
        rows = [
            [
                item['class'].name,
                item['class'].department.code if item['class'].department else 'N/A',
                item['class'].semester,
                item['class'].academic_year,
                item['students_count'],
                item['sessions_count'],
                item['present_count'],
                item['absent_count'],
                item['percentage']
            ]
            for item in report['classes_data']
        ]
        filename = "class_attendance_summary_report.csv"

    return ReportService.build_csv_response(headers, rows, filename)


# --- Subject Attendance Reports ---

@admin_bp.route('/reports/subjects')
@admin_required
def subject_reports():
    """Subject-wise attendance report with course catalog filters."""
    dept_id = request.args.get('department_id', type=int)
    class_id = request.args.get('class_id', type=int)
    subject_id = request.args.get('subject_id', type=int)
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    df, dt, d_err = validate_date_range(date_from, date_to)
    if d_err:
        flash(d_err, "warning")
        date_from = ""
        date_to = ""

    report = ReportService.get_subject_attendance_report(dept_id, class_id, subject_id, date_from, date_to)
    departments = Department.query.order_by(Department.code.asc()).all()
    classes = Class.query.order_by(Class.name.asc()).all()
    subjects = Subject.query.order_by(Subject.code.asc()).all()

    return render_template(
        'admin/reports/subjects.html',
        report=report,
        departments=departments,
        classes=classes,
        subjects=subjects,
        selected_dept=dept_id,
        selected_class=class_id,
        selected_subject=subject_id,
        date_from=date_from,
        date_to=date_to
    )


@admin_bp.route('/reports/subjects/export.csv')
@admin_required
def export_subject_reports_csv():
    """Export filtered subject attendance report as CSV."""
    dept_id = request.args.get('department_id', type=int)
    class_id = request.args.get('class_id', type=int)
    subject_id = request.args.get('subject_id', type=int)
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    df, dt, d_err = validate_date_range(date_from, date_to)
    if d_err:
        date_from = ""
        date_to = ""

    report = ReportService.get_subject_attendance_report(dept_id, class_id, subject_id, date_from, date_to)

    if subject_id and report['student_details']:
        sub_obj = db.session.get(Subject, subject_id)
        sub_code = sub_obj.code if sub_obj else f"Subject_{subject_id}"
        headers = ["Roll Number", "Student Name", "Subject Code", "Subject Name", "Attended", "Absent", "Total Sessions", "Turnout %", "Status"]
        rows = [
            [
                item['student'].roll_number,
                item['student'].full_name,
                item['subject'].code,
                item['subject'].name,
                item['present'],
                item['absent'],
                item['total'],
                item['percentage'],
                item['status']
            ]
            for item in report['student_details']
        ]
        filename = f"subject_{sub_code}_attendance_report.csv"
    else:
        headers = ["Subject Code", "Subject Name", "Department", "Semester", "Credits", "Sessions Conducted", "Present Marks", "Absent Marks", "Turnout %"]
        rows = [
            [
                item['subject'].code,
                item['subject'].name,
                item['subject'].department.code if item['subject'].department else 'N/A',
                item['subject'].semester,
                item['subject'].credits,
                item['sessions_count'],
                item['present_count'],
                item['absent_count'],
                item['percentage']
            ]
            for item in report['subjects_data']
        ]
        filename = "subject_attendance_summary_report.csv"

    return ReportService.build_csv_response(headers, rows, filename)


# --- Faculty Attendance Activity Reports ---

@admin_bp.route('/reports/faculty')
@admin_required
def faculty_reports():
    """Faculty attendance activity report."""
    dept_id = request.args.get('department_id', type=int)
    faculty_id = request.args.get('faculty_id', type=int)
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    df, dt, d_err = validate_date_range(date_from, date_to)
    if d_err:
        flash(d_err, "warning")
        date_from = ""
        date_to = ""

    activity_data = ReportService.get_faculty_activity_report(dept_id, faculty_id, date_from, date_to)
    departments = Department.query.order_by(Department.code.asc()).all()
    faculty_list = FacultyProfile.query.order_by(FacultyProfile.full_name.asc()).all()

    return render_template(
        'admin/reports/faculty.html',
        activity_data=activity_data,
        departments=departments,
        faculty_list=faculty_list,
        selected_dept=dept_id,
        selected_faculty=faculty_id,
        date_from=date_from,
        date_to=date_to
    )


@admin_bp.route('/reports/faculty/export.csv')
@admin_required
def export_faculty_reports_csv():
    """Export faculty attendance activity report as CSV."""
    dept_id = request.args.get('department_id', type=int)
    faculty_id = request.args.get('faculty_id', type=int)
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    df, dt, d_err = validate_date_range(date_from, date_to)
    if d_err:
        date_from = ""
        date_to = ""

    activity_data = ReportService.get_faculty_activity_report(dept_id, faculty_id, date_from, date_to)

    headers = [
        "Employee ID", "Faculty Name", "Department", "Designation",
        "Assigned Classes", "Assigned Subjects", "Sessions Conducted",
        "Total Records", "Average Turnout %"
    ]
    rows = [
        [
            item['faculty'].employee_id,
            item['faculty'].full_name,
            item['faculty'].department.code if item['faculty'].department else 'N/A',
            item['faculty'].designation,
            "; ".join(item['assigned_classes_list']),
            "; ".join(item['assigned_subjects_list']),
            item['sessions_conducted'],
            item['total_records'],
            item['average_turnout']
        ]
        for item in activity_data
    ]

    return ReportService.build_csv_response(headers, rows, "faculty_activity_report.csv")


# --- Student Attendance Reports ---

@admin_bp.route('/reports/students')
@admin_required
def student_reports():
    """Global student attendance audit report."""
    search = request.args.get('search', '').strip()
    dept_id = request.args.get('department_id', type=int)
    class_id = request.args.get('class_id', type=int)
    subject_id = request.args.get('subject_id', type=int)

    report_data, threshold = ReportService.get_student_attendance_report(search, dept_id, class_id, subject_id)
    departments = Department.query.order_by(Department.code.asc()).all()
    classes = Class.query.order_by(Class.name.asc()).all()
    subjects = Subject.query.order_by(Subject.code.asc()).all()

    return render_template(
        'admin/reports/students.html',
        report_data=report_data,
        threshold=threshold,
        departments=departments,
        classes=classes,
        subjects=subjects,
        search=search,
        selected_dept=dept_id,
        selected_class=class_id,
        selected_subject=subject_id
    )


@admin_bp.route('/reports/students/export.csv')
@admin_required
def export_student_reports_csv():
    """Export global student attendance audit as CSV."""
    search = request.args.get('search', '').strip()
    dept_id = request.args.get('department_id', type=int)
    class_id = request.args.get('class_id', type=int)
    subject_id = request.args.get('subject_id', type=int)

    report_data, threshold = ReportService.get_student_attendance_report(search, dept_id, class_id, subject_id)

    headers = [
        "Roll Number", "Student Name", "Email", "Department",
        "Class", "Curriculum Context", "Attended", "Absent",
        "Total Sessions", "Turnout %", "Threshold %", "Status"
    ]
    rows = [
        [
            item['student'].roll_number,
            item['student'].full_name,
            item['student'].user.email if item['student'].user else '',
            item['student'].department.code if item['student'].department else 'N/A',
            item['student'].enrolled_class.name if item['student'].enrolled_class else 'N/A',
            item['subject_label'],
            item['present'],
            item['absent'],
            item['total'],
            item['percentage'],
            item['threshold'],
            item['status']
        ]
        for item in report_data
    ]

    return ReportService.build_csv_response(headers, rows, "student_attendance_audit_report.csv")


# --- Institutional Defaulters Report ---

@admin_bp.route('/reports/defaulters')
@admin_required
def defaulter_reports():
    """Institutional attendance shortage and defaulters report."""
    dept_id = request.args.get('department_id', type=int)
    class_id = request.args.get('class_id', type=int)
    subject_id = request.args.get('subject_id', type=int)
    raw_thresh = request.args.get('threshold')
    custom_threshold = None
    if raw_thresh is not None and str(raw_thresh).strip() != '':
        th_val, th_err = validate_threshold(raw_thresh)
        if th_err:
            flash(th_err, "warning")
        else:
            custom_threshold = th_val

    defaulters, threshold = ReportService.get_institutional_defaulters_report(
        dept_id, class_id, subject_id, custom_threshold
    )
    departments = Department.query.order_by(Department.code.asc()).all()
    classes = Class.query.order_by(Class.name.asc()).all()
    subjects = Subject.query.order_by(Subject.code.asc()).all()

    return render_template(
        'admin/reports/defaulters.html',
        defaulters=defaulters,
        threshold=threshold,
        departments=departments,
        classes=classes,
        subjects=subjects,
        selected_dept=dept_id,
        selected_class=class_id,
        selected_subject=subject_id
    )


@admin_bp.route('/reports/defaulters/export.csv')
@admin_required
def export_defaulter_reports_csv():
    """Export institutional defaulter list as CSV."""
    dept_id = request.args.get('department_id', type=int)
    class_id = request.args.get('class_id', type=int)
    subject_id = request.args.get('subject_id', type=int)
    raw_thresh = request.args.get('threshold')
    custom_threshold = None
    if raw_thresh is not None and str(raw_thresh).strip() != '':
        th_val, th_err = validate_threshold(raw_thresh)
        if not th_err:
            custom_threshold = th_val

    defaulters, threshold = ReportService.get_institutional_defaulters_report(
        dept_id, class_id, subject_id, custom_threshold
    )

    headers = [
        "Roll Number", "Student Name", "Department", "Class",
        "Subject Code", "Subject Name", "Attended", "Total Sessions",
        "Turnout %", "Required Cutoff %", "Shortage Deficit %"
    ]
    rows = [
        [
            item['student'].roll_number,
            item['student'].full_name,
            item['student'].department.code if item['student'].department else 'N/A',
            item['class'].name if item['class'] else 'N/A',
            item['subject'].code if item['subject'] else 'N/A',
            item['subject'].name if item['subject'] else 'N/A',
            item['attended'],
            item['total'],
            item['percentage'],
            item['threshold'],
            item['shortage']
        ]
        for item in defaulters
    ]

    return ReportService.build_csv_response(headers, rows, "institutional_defaulters_report.csv")
