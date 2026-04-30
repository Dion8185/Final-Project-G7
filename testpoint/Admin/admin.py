from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
import mysql.connector
from testpoint import db_config
from testpoint.Auth.login import admin_logged_in
from werkzeug.security import generate_password_hash

admin = Blueprint('admin', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/admin/static')

@admin.route('/admin_dashboard')
def admin_dashboard():
    if admin_logged_in():
        firstname = session.get('firstname')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        try:
            # 1. Summary Card Data
            cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_active = 1")
            total_users = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM courses WHERE is_active = 1")
            total_courses = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM exams")
            total_exams = cursor.fetchone()['count']

            # Live Data: Students currently taking an exam
            cursor.execute("SELECT COUNT(*) as count FROM exam_attempts WHERE status = 'in-progress'")
            live_sessions = cursor.fetchone()['count']

            # System Integrity: Total cheating violations detected
            cursor.execute("SELECT SUM(tab_switches) as total FROM exam_attempts")
            global_violations = cursor.fetchone()['total'] or 0

            # 2. Pie Chart: User Distribution
            cursor.execute("SELECT role, COUNT(*) as count FROM users WHERE is_active = 1 GROUP BY role")
            role_data = cursor.fetchall()
            pie_labels = [r['role'].capitalize() for r in role_data]
            pie_values = [r['count'] for r in role_data]

            # 3. Dynamic Progress Bars: Course Popularity (Joined via Classes)
            cursor.execute("""
                SELECT c.course_name, COUNT(e.enrollment_id) as student_count 
                FROM courses c 
                JOIN classes cl ON c.course_code = cl.course_code
                LEFT JOIN enrollments e ON cl.class_code = e.class_code 
                GROUP BY c.course_code 
                ORDER BY student_count DESC LIMIT 3
            """)
            top_courses = cursor.fetchall()

        finally:
            cursor.close()
            connection.close()

        return render_template('admin_dashboard.html', 
                               firstname=firstname,
                               total_users=total_users,
                               total_courses=total_courses,
                               total_exams=total_exams,
                               live_sessions=live_sessions,
                               global_violations=global_violations,
                               pie_labels=pie_labels,
                               pie_values=pie_values,
                               top_courses=top_courses)
    return redirect(url_for('auth.login'))


#! 1. MANAGE ACCOUNTS (Modified to handle Blocks)
@admin.route('/manage_accounts' )
def manage_accounts():
    if admin_logged_in():
        firstname = session.get('firstname') 
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        cursor.execute(""" SELECT 
                            u.user_id,
                            COALESCE(s.firstname, t.firstname, a.firstname) AS firstname,
                            COALESCE(s.middlename, t.middlename, a.middlename) AS middlename,
                            COALESCE(s.lastname, t.lastname, a.lastname) AS lastname,
                            u.email, u.role, u.is_verified, u.created_at,
                            b.block_name, p.program_name
                            FROM users u
                            LEFT JOIN students s ON u.user_id = s.student_id
                            LEFT JOIN blocks b ON s.block_id = b.block_id
                            LEFT JOIN programs p ON b.program_id = p.program_id
                            LEFT JOIN teachers t ON u.user_id = t.teacher_id
                            LEFT JOIN admins a ON u.user_id = a.admin_id
                            WHERE u.is_active = 1;
        """)
        users = cursor.fetchall()
        
        # Fetch all blocks for the dropdown in modals
        cursor.execute("SELECT b.block_id, b.block_name, p.program_name FROM blocks b JOIN programs p ON b.program_id = p.program_id")
        blocks = cursor.fetchall()
        
        cursor.close(); connection.close()
        return render_template('admin_accounts.html', users=users, blocks=blocks, firstname=firstname)
    else:
        flash('Please log in as admin.', 'danger')
        return redirect(url_for('auth.login'))

@admin.route('/get_user_courses/<string:user_id>')
def get_user_courses(user_id):
    if not admin_logged_in(): return {"error": "Unauthorized"}, 401
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT role FROM users WHERE user_id = %s", (user_id,))
    user = cursor.fetchone()
    if not user: return {"error": "User not found"}, 404
        
    role = user['role'].lower(); data = []; label = ""
    if role == 'student':
        label = "Enrolled Classes"
        cursor.execute("""
            SELECT cl.class_code, c.course_name 
            FROM classes cl
            JOIN courses c ON cl.course_code = c.course_code
            JOIN enrollments e ON cl.class_code = e.class_code
            WHERE e.student_id = %s
        """, (user_id,))
        data = cursor.fetchall()
    elif role == 'teacher':
        label = "Assigned Classes"
        cursor.execute("""
            SELECT cl.class_code, c.course_name 
            FROM classes cl
            JOIN courses c ON cl.course_code = c.course_code
            WHERE cl.teacher_id = %s AND cl.is_active = 1
        """, (user_id,))
        data = cursor.fetchall()
    
    cursor.close(); connection.close()
    return {"role": role, "label": label, "items": data}

@admin.route('/trashed_accounts')
def trashed_accounts():
    if admin_logged_in():
        firstname = session.get('firstname') 
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        cursor.execute(""" SELECT 
                            u.user_id,
                            COALESCE(s.firstname, t.firstname) AS firstname,
                            COALESCE(s.middlename, t.middlename) AS middlename,
                            COALESCE(s.lastname, t.lastname) AS lastname,
                            u.email, u.role, u.is_verified, u.created_at
                            FROM users u
                            LEFT JOIN students s ON u.user_id = s.student_id
                            LEFT JOIN teachers t ON u.user_id = t.teacher_id
                            WHERE u.is_active = 0;
        """)
        trashed_users = cursor.fetchall()
        cursor.close(); connection.close()
        return render_template('admin_trashed.html', trashed_users=trashed_users, firstname=firstname)
    return redirect(url_for('auth.login'))

@admin.route('/update_account/<string:user_id>', methods=['POST'])
def update_account(user_id):
    if admin_logged_in():
        firstname = request.form.get('firstname'); middlename = request.form.get('middlename'); lastname = request.form.get('lastname')
        email = request.form.get('email'); is_verified = request.form.get('status'); role = request.form.get('role')
        block_id = request.form.get('block_id')
        new_password = request.form.get('password'); confirm_password = request.form.get('confirm_password')

        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        try:
            if new_password:
                if new_password != confirm_password:
                    flash('Passwords do not match.', 'danger'); return redirect(url_for('admin.manage_accounts'))
                hashed_pw = generate_password_hash(new_password)
                cursor.execute("UPDATE users SET email = %s, is_verified = %s, password = %s WHERE user_id = %s", (email, is_verified, hashed_pw, user_id))
            else:
                cursor.execute("UPDATE users SET email = %s, is_verified = %s WHERE user_id = %s", (email, is_verified, user_id))

            if role == 'teacher':
                cursor.execute("UPDATE teachers SET firstname = %s, middlename = %s, lastname = %s WHERE teacher_id = %s", (firstname, middlename, lastname, user_id))
            elif role == 'student':
                b_id = block_id if block_id != "" else None
                cursor.execute("UPDATE students SET firstname = %s, middlename = %s, lastname = %s, block_id = %s WHERE student_id = %s", (firstname, middlename, lastname, b_id, user_id))
            elif role == 'admin':
                cursor.execute("UPDATE admins SET firstname = %s, middlename = %s, lastname = %s WHERE admin_id = %s", (firstname, middlename, lastname, user_id))
            connection.commit(); flash('Account updated successfully.', 'success')
        except mysql.connector.Error as err:
            connection.rollback(); flash(f'Database Error: {err}', 'danger')
        finally:
            cursor.close(); connection.close()
        return redirect(url_for('admin.manage_accounts'))
    return redirect(url_for('auth.login'))

@admin.route('/add_user', methods=['GET', 'POST'])
def add_user():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    if request.method == 'POST':
        fname = request.form.get('firstname'); mname = request.form.get('middlename'); lname = request.form.get('lastname')
        email = request.form.get('email'); password = request.form.get('password'); role = request.form.get('role', 'student').lower()
        is_verified = request.form.get('status', 1); block_id = request.form.get('block_id')
        
        prefix = {'admin': 'A', 'teacher': 'T', 'student': 'S'}.get(role, 'U')
        custom_user_id = generate_id(prefix); hashed_password = generate_password_hash(password)
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        try:
            cursor.execute("SELECT user_id FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                flash('User with this email already exists.', 'danger'); return redirect(url_for('admin.manage_accounts'))

            cursor.execute("INSERT INTO users (user_id, email, password, role, is_verified) VALUES (%s, %s, %s, %s, %s)", (custom_user_id, email, hashed_password, role, is_verified))

            if role == 'teacher':
                cursor.execute("INSERT INTO teachers (teacher_id, firstname, middlename, lastname, email) VALUES (%s, %s, %s, %s, %s)", (custom_user_id, fname, mname, lname, email))
            elif role == 'student':
                b_id = block_id if block_id != "" else None
                cursor.execute("INSERT INTO students (student_id, firstname, middlename, lastname, email, block_id) VALUES (%s, %s, %s, %s, %s, %s)", (custom_user_id, fname, mname, lname, email, b_id))
            elif role == 'admin':
                cursor.execute("INSERT INTO admins (admin_id, firstname, middlename, lastname, email) VALUES (%s, %s, %s, %s, %s)", (custom_user_id, fname, mname, lname, email))
            connection.commit(); flash(f'Account created successfully! ID: {custom_user_id}', 'success')
        finally:
            cursor.close(); connection.close()
        return redirect(url_for('admin.manage_accounts'))
    return render_template('admin_accounts.html')

def generate_id(role_prefix):
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    year_suffix = datetime.now().strftime("%y") 
    like_pattern = f"{role_prefix}{year_suffix}-%"
    cursor.execute("SELECT user_id FROM users WHERE user_id LIKE %s ORDER BY user_id DESC LIMIT 1", (like_pattern,))
    result = cursor.fetchone()
    new_num = (int(result[0].split('-')[1]) + 1) if result else 1
    cursor.close(); connection.close()
    return f"{role_prefix}{year_suffix}-{str(new_num).zfill(4)}"

@admin.route('/delete_account/<string:user_id>', methods=['POST'])
def delete_account(user_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("UPDATE users SET is_active = 0 WHERE user_id = %s", (user_id,))
        connection.commit(); cursor.close(); connection.close()
        flash('Account deleted successfully.', 'success')
        return redirect(url_for('admin.manage_accounts'))
    return redirect(url_for('auth.login'))
    
@admin.route('/restore_account/<string:user_id>', methods=['POST'])
def restore_account(user_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("UPDATE users SET is_active = 1 WHERE user_id = %s", (user_id,))
        connection.commit(); cursor.close(); connection.close()
        flash('Account restored successfully.', 'success')
        return redirect(url_for('admin.trashed_accounts'))
    return redirect(url_for('auth.login'))
    
@admin.route('/delete_account_permanently/<string:user_id>', methods=['POST'])
def delete_account_permanently(user_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        connection.commit(); cursor.close(); connection.close()
        flash('Account deleted permanently.', 'success')
        return redirect(url_for('admin.manage_accounts'))
    return redirect(url_for('auth.login'))

@admin.route('/empty_trash', methods=['POST'])
def empty_trash():
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("DELETE FROM users WHERE is_active = 0")
        connection.commit(); cursor.close(); connection.close()
        flash('Trash emptied successfully.', 'success')
        return redirect(url_for('admin.trashed_accounts'))
    return redirect(url_for('auth.login'))


#! 2. MANAGE PROGRAMS (NEW)
@admin.route('/manage_programs', methods=['GET', 'POST'])
def manage_programs():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    if request.method == 'POST':
        name = request.form.get('program_name'); desc = request.form.get('description')
        cursor.execute("INSERT INTO programs (program_name, description) VALUES (%s, %s)", (name, desc))
        connection.commit(); flash("Program added.", "success"); return redirect(url_for('admin.manage_programs'))
    
    cursor.execute("SELECT * FROM programs"); progs = cursor.fetchall()
    cursor.close(); connection.close()
    return render_template('admin_programs.html', programs=progs, firstname=session.get('firstname'))


#! 3. MANAGE BLOCKS (NEW)
@admin.route('/manage_blocks', methods=['GET', 'POST'])
def manage_blocks():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    if request.method == 'POST':
        p_id = request.form.get('program_id'); name = request.form.get('block_name')
        cursor.execute("INSERT INTO blocks (program_id, block_name) VALUES (%s, %s)", (p_id, name))
        connection.commit(); flash("Block created.", "success"); return redirect(url_for('admin.manage_blocks'))
    
    cursor.execute("SELECT b.*, p.program_name FROM blocks b JOIN programs p ON b.program_id = p.program_id")
    blks = cursor.fetchall()
    cursor.execute("SELECT * FROM programs"); progs = cursor.fetchall()
    cursor.close(); connection.close()
    return render_template('admin_blocks.html', blocks=blks, programs=progs, firstname=session.get('firstname'))

@admin.route('/delete_block/<int:block_id>', methods=['POST'])
def delete_block(block_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("DELETE FROM blocks WHERE block_id = %s", (block_id,))
        connection.commit(); cursor.close(); connection.close()
        flash('Block deleted successfully.', 'success')
        return redirect(url_for('admin.manage_blocks'))
    return redirect(url_for('auth.login'))


#! 4. MANAGE COURSES (Master Subject Catalog - course_code is PK)
@admin.route('/manage_courses')
def manage_courses():
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM courses WHERE is_active = 1 ORDER BY course_code ASC")
        courses = cursor.fetchall()
        cursor.close(); connection.close()
        return render_template('admin_courses.html', courses=courses, firstname=session.get('firstname'))
    return redirect(url_for('auth.login'))

@admin.route('/add_course', methods=['POST'])
def add_course():
    if admin_logged_in():
        code = request.form.get('course_code'); name = request.form.get('course_name'); desc = request.form.get('description')
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        try:
            cursor.execute("INSERT INTO courses (course_code, course_name, description) VALUES (%s, %s, %s)", (code, name, desc))
            connection.commit(); flash(f'Subject {code} added to catalog.', 'success')
        except mysql.connector.Error as err: flash(f'Error: {err}', 'danger')
        finally: cursor.close(); connection.close()
        return redirect(url_for('admin.manage_courses'))
    return redirect(url_for('auth.login'))

@admin.route('/update_course/<string:old_code>', methods=['POST'])
def update_course(old_code):
    if admin_logged_in():
        new_code = request.form.get('course_code'); name = request.form.get('course_name'); desc = request.form.get('description')
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        try:
            cursor.execute("UPDATE courses SET course_code = %s, course_name = %s, description = %s WHERE course_code = %s", (new_code, name, desc, old_code))
            connection.commit(); flash('Subject updated.', 'success')
        finally: cursor.close(); connection.close()
        return redirect(url_for('admin.manage_courses'))
    return redirect(url_for('auth.login'))

@admin.route('/deactivate_course/<string:course_code>', methods=['POST'])
def deactivate_course(course_code):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("UPDATE courses SET is_active = 0 WHERE course_code = %s", (course_code,))
        connection.commit(); cursor.close(); connection.close()
        flash('Subject moved to trash.', 'success'); return redirect(url_for('admin.manage_courses'))
    return redirect(url_for('auth.login'))

@admin.route('/trashed_courses')
def trashed_courses():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM courses WHERE is_active = 0 ORDER BY course_code ASC")
    trashed = cursor.fetchall(); cursor.close(); connection.close()
    return render_template('admin_trashed_courses.html', trashed_courses=trashed, firstname=session.get('firstname'))

@admin.route('/restore_course/<string:course_code>', methods=['POST'])
def restore_course(course_code):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("UPDATE courses SET is_active = 1 WHERE course_code = %s", (course_code,))
        connection.commit(); cursor.close(); connection.close()
        flash('Subject restored.', 'success'); return redirect(url_for('admin.manage_courses'))
    return redirect(url_for('auth.login'))

@admin.route('/delete_course_permanently/<string:course_code>', methods=['POST'])
def delete_course_permanently(course_code):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("DELETE FROM courses WHERE course_code = %s", (course_code,))
        connection.commit(); cursor.close(); connection.close()
        flash('Subject deleted permanently.', 'success'); return redirect(url_for('admin.trashed_courses'))
    return redirect(url_for('auth.login'))

@admin.route('/empty_course_trash', methods=['POST'])
def empty_course_trash():
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("DELETE FROM courses WHERE is_active = 0")
        connection.commit(); cursor.close(); connection.close()
        flash('Subject trash emptied.', 'success'); return redirect(url_for('admin.trashed_courses'))
    return redirect(url_for('auth.login'))

#! 5. MANAGE CLASSES (The Link: Subject + Block + Teacher)
@admin.route('/manage_classes', methods=['GET', 'POST'])
def manage_classes():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    if request.method == 'POST':
        cl_code = request.form.get('class_code'); co_code = request.form.get('course_code')
        b_id = request.form.get('block_id'); t_id = request.form.get('teacher_id')
        try:
            cursor.execute("INSERT INTO classes (class_code, course_code, block_id, teacher_id) VALUES (%s, %s, %s, %s)", (cl_code, co_code, b_id, t_id))
            connection.commit(); flash("Class scheduled successfully.", "success")
        except mysql.connector.Error as err: flash(f"Error: {err}", "danger")
        return redirect(url_for('admin.manage_classes'))

    cursor.execute("""
        SELECT cl.*, c.course_name, b.block_name, p.program_name, t.firstname, t.lastname
        FROM classes cl
        JOIN courses c ON cl.course_code = c.course_code
        JOIN blocks b ON cl.block_id = b.block_id
        JOIN programs p ON b.program_id = p.program_id
        LEFT JOIN teachers t ON cl.teacher_id = t.teacher_id
    """)
    classes = cursor.fetchall()
    cursor.execute("SELECT course_code, course_name FROM courses WHERE is_active = 1")
    subjects = cursor.fetchall()
    cursor.execute("SELECT b.block_id, b.block_name, p.program_name FROM blocks b JOIN programs p ON b.program_id = p.program_id")
    blocks = cursor.fetchall()
    cursor.execute("SELECT teacher_id, firstname, lastname FROM teachers")
    teachers = cursor.fetchall()
    
    cursor.close(); connection.close()
    return render_template('admin_classes.html', classes=classes, subjects=subjects, blocks=blocks, teachers=teachers, firstname=session.get('firstname'))


#! 6. BULK ENROLLMENT (By Block)
@admin.route('/enroll_block', methods=['POST'])
def enroll_block():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    class_code = request.form.get('class_code')
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT block_id FROM classes WHERE class_code = %s", (class_code,))
        class_info = cursor.fetchone()
        if class_info:
            cursor.execute("""
                INSERT IGNORE INTO enrollments (student_id, class_code)
                SELECT student_id, %s FROM students WHERE block_id = %s
            """, (class_code, class_info['block_id']))
            connection.commit(); flash(f"Block enrolled into {class_code}.", "success")
    finally:
        cursor.close(); connection.close()
    return redirect(url_for('admin.manage_classes'))


#! 7. OVERSEE EXAMS (Linked to Class Code)
@admin.route('/oversee_exams')
def oversee_exams():
    if admin_logged_in():
        firstname = session.get('firstname')
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT e.*, cl.course_code, c.course_name, b.block_name, t.firstname as teacher_fname, t.lastname as teacher_lname,
            (SELECT SUM(tab_switches) FROM exam_attempts WHERE exam_id = e.exam_id) as total_violations,
            (SELECT COUNT(*) FROM exam_attempts WHERE exam_id = e.exam_id AND status = 'in-progress') as active_count
            FROM exams e 
            JOIN classes cl ON e.class_code = cl.class_code
            JOIN courses c ON cl.course_code = c.course_code
            JOIN blocks b ON cl.block_id = b.block_id
            JOIN teachers t ON cl.teacher_id = t.teacher_id
            ORDER BY e.date_time DESC
        """)
        exams = cursor.fetchall()
        for exam in exams:
            exam['is_live'] = exam['is_active'] == 1 and exam['active_count'] > 0
            exam['teacher_full_name'] = f"{exam['teacher_fname']} {exam['teacher_lname']}"
            if exam['total_violations'] is None: exam['total_violations'] = 0
        cursor.close(); connection.close()
        return render_template('admin_exams.html', exams=exams, firstname=firstname)
    return redirect(url_for('auth.login'))


#! 8. SYSTEM LOGS
@admin.route('/user_logs')
def user_logs():
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT user_id, email, role, created_at FROM users ORDER BY created_at DESC")
        users = cursor.fetchall()
        for user in users:
            role = (user.get("role") or "").lower()
            user["role_class"] = {"admin": "danger", "teacher": "primary", "student": "success"}.get(role, "secondary")
        cursor.close(); connection.close()
        return render_template('admin_logs.html', user_logs=users)
    return redirect(url_for('auth.login'))


#! 9. SETTINGS
@admin.route('/settings')
def settings():
    if admin_logged_in():
        return render_template('admin_settings.html', firstname=session.get('firstname'))
    return redirect(url_for('auth.login'))


#! 10. PROFILE
@admin.route('/profile', methods=['GET', 'POST'])
def profile():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    user_id = session.get('user_id'); connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    if request.method == 'POST':
        fname = request.form.get('firstname'); mname = request.form.get('middlename'); lname = request.form.get('lastname')
        new_pw = request.form.get('password'); conf_pw = request.form.get('confirm_password')
        try:
            cursor.execute("UPDATE admins SET firstname = %s, middlename = %s, lastname = %s WHERE admin_id = %s", (fname, mname, lname, user_id))
            if new_pw:
                if new_pw == conf_pw:
                    cursor.execute("UPDATE users SET password = %s WHERE user_id = %s", (generate_password_hash(new_pw), user_id))
                else:
                    flash('Passwords do not match.', 'warning'); return redirect(url_for('admin.profile'))
            connection.commit(); flash('Profile updated.', 'success')
        finally:
            cursor.close(); connection.close()
        return redirect(url_for('admin.profile'))
    cursor.execute("SELECT u.*, a.* FROM users u JOIN admins a ON u.user_id = a.admin_id WHERE u.user_id = %s", (user_id,))
    user_data = cursor.fetchone(); cursor.close(); connection.close()
    return render_template('admin_profile.html', user=user_data)


#! 11. ENROLLMENT MANAGEMENT
@admin.route('/manage_enrollments/<string:class_code>')
def manage_enrollments(class_code):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT cl.*, c.course_name FROM classes cl 
            JOIN courses c ON cl.course_code = c.course_code 
            WHERE cl.class_code = %s
        """, (class_code,))
        class_info = cursor.fetchone()
        cursor.execute("""
            SELECT s.student_id, s.firstname, s.lastname, s.email, e.enrollment_id, e.enrolled_at
            FROM students s
            JOIN enrollments e ON s.student_id = e.student_id
            WHERE e.class_code = %s
        """, (class_code,))
        enrollees = cursor.fetchall()
        cursor.execute("""
            SELECT s.student_id, s.firstname, s.lastname
            FROM students s
            LEFT JOIN enrollments e ON s.student_id = e.student_id AND e.class_code = %s
            WHERE e.student_id IS NULL AND s.student_id IN (SELECT user_id FROM users WHERE is_verified = 1 AND is_active = 1)
        """, (class_code,))
        all_students = cursor.fetchall()
        cursor.close(); connection.close()
        return render_template('admin_enrollees.html', class_info=class_info, enrollees=enrollees, all_students=all_students)
    return redirect(url_for('auth.login'))

@admin.route('/enroll_student', methods=['POST'])
def enroll_student():
    if admin_logged_in():
        student_id = request.form.get('student_id'); class_code = request.form.get('class_code')
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        try:
            cursor.execute("INSERT INTO enrollments (student_id, class_code) VALUES (%s, %s)", (student_id, class_code))
            connection.commit(); flash('Student enrolled.', 'success')
        finally:
            cursor.close(); connection.close()
        return redirect(url_for('admin.manage_enrollments', class_code=class_code))
    return redirect(url_for('auth.login'))

@admin.route('/unenroll_student/<int:enrollment_id>/<string:class_code>', methods=['POST'])
def unenroll_student(enrollment_id, class_code):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("DELETE FROM enrollments WHERE enrollment_id = %s", (enrollment_id,))
        connection.commit(); cursor.close(); connection.close()
        flash('Student removed.', 'success'); return redirect(url_for('admin.manage_enrollments', class_code=class_code))
    return redirect(url_for('auth.login'))


#! 12. VERIFICATIONS
@admin.route('/verifications')
def view_verifications():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM pending_users WHERE verification_status = 'pending_approval' OR verification_status = 'pending_upload' ORDER BY created_at DESC")
    pending_list = cursor.fetchall()
    
    cursor.close()
    connection.close()
    return render_template('admin_verifications.html', pending_list=pending_list, firstname=session.get('firstname'))