from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
import mysql.connector
from testpoint import db_config
from testpoint.Auth.login import admin_logged_in
from werkzeug.security import generate_password_hash

admin = Blueprint('admin', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/admin/static')

@admin.route('/')
def admin_dashboard():
    
    if admin_logged_in():
        user_id = session.get('user_id')
        email = session.get('email')
        role = session.get('role')
        firstname = session.get('firstname') 
        
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.close()
        connection.close()
        return render_template('admin_dashboard.html', user_id=user_id, email=email, role=role, firstname=firstname, total_users=total_users )
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))


#! MANAGE ACCOUNTS
@admin.route('/manage_accounts' )
def manage_accounts():
    
    if admin_logged_in():
        firstname = session.get('firstname') 
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute(""" SELECT 
                            u.user_id,
                            -- Choose name from students or teachers
                            COALESCE(s.firstname, t.firstname, a.firstname) AS firstname,
                            COALESCE(s.middlename, t.middlename, a.middlename) AS middlename,
                            COALESCE(s.lastname, t.lastname, a.lastname) AS lastname,
                            u.email,
                            u.role,
                            u.is_verified,
                            u.created_at
                            FROM users u
                            LEFT JOIN students s
                                ON u.user_id = s.student_id
                            LEFT JOIN teachers t
                                ON u.user_id = t.teacher_id
                            LEFT JOIN admins a
                                ON u.user_id = a.admin_id
                            WHERE u.is_active = 1;
        """)
        users = cursor.fetchall()
        cursor.close()
        connection.close()
    
        return render_template('admin_accounts.html', users=users, firstname=firstname)
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))

@admin.route('/trashed_accounts')
def trashed_accounts():
    if admin_logged_in():
        firstname = session.get('firstname') 
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute(""" SELECT 
                            u.user_id,
                            -- Choose name from students or teachers
                            COALESCE(s.firstname, t.firstname) AS firstname,
                            COALESCE(s.middlename, t.middlename) AS middlename,
                            COALESCE(s.lastname, t.lastname) AS lastname,
                            u.email,
                            u.role,
                            u.is_verified,
                            u.created_at
                            FROM users u
                            LEFT JOIN students s
                                ON u.user_id = s.student_id
                            LEFT JOIN teachers t
                                ON u.user_id = t.teacher_id
                            WHERE u.is_active = NULL OR u.is_active = 0;
        """)
        trashed_users = cursor.fetchall()
        cursor.close()
        connection.close()
        
        return render_template('admin_trashed.html', trashed_users=trashed_users, firstname=firstname)
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))

@admin.route('/update_account/<string:user_id>', methods=['POST'])
def update_account(user_id):
    if admin_logged_in():
        firstname = request.form.get('firstname')
        middlename = request.form.get('middlename')
        lastname = request.form.get('lastname')
        email = request.form.get('email')
        is_verified = request.form.get('status')
        role = request.form.get('role')
        
        new_password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()

        try:
           
            if new_password:
                if new_password != confirm_password:
                    flash('Passwords do not match.', 'danger')
                    return redirect(url_for('admin.manage_accounts'))
                
                hashed_pw = generate_password_hash(new_password)
                update_user_query = "UPDATE users SET email = %s, is_verified = %s, password = %s WHERE user_id = %s"
                cursor.execute(update_user_query, (email, is_verified, hashed_pw, user_id))
            else:
                
                update_user_query = "UPDATE users SET email = %s, is_verified = %s WHERE user_id = %s"
                cursor.execute(update_user_query, (email, is_verified, user_id))

            if role == 'teacher':
                update_profile_query = """
                    UPDATE teachers 
                    SET firstname = %s, middlename = %s, lastname = %s
                    WHERE teacher_id = %s
                """
                cursor.execute(update_profile_query, (firstname, middlename, lastname, user_id))
            
            elif role == 'student':
                update_profile_query = """
                    UPDATE students 
                    SET firstname = %s, middlename = %s, lastname = %s
                    WHERE student_id = %s
                """
                cursor.execute(update_profile_query, (firstname, middlename, lastname, user_id))
            
            elif role == 'admin':
                update_profile_query = """
                    UPDATE admins 
                    SET firstname = %s, middlename = %s, lastname = %s
                    WHERE admin_id = %s
                """
                cursor.execute(update_profile_query, (firstname, middlename, lastname, user_id))

            connection.commit()
            flash('Account updated successfully.', 'success')

        except mysql.connector.Error as err:
            connection.rollback()
            flash(f'Database Error: {err}', 'danger')
        
        finally:
            cursor.close()
            connection.close()
        
        return redirect(url_for('admin.manage_accounts'))
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))

@admin.route('/add_user', methods=['GET', 'POST'])
def add_user():
    if not admin_logged_in():
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        firstname = request.form.get('firstname')
        middlename = request.form.get('middlename')
        lastname = request.form.get('lastname')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'student').lower()
        is_verified = request.form.get('status', 1)
        
        region = request.form.get('region_text')
        province = request.form.get('province_text')
        city = request.form.get('city_text')
        barangay = request.form.get('barangay_text')
    

        role_prefixes = {
            'admin': 'A',
            'teacher': 'T',
            'student': 'S'
        }
        prefix = role_prefixes.get(role, 'U')
        custom_user_id = generate_id(prefix)

        hashed_password = generate_password_hash(password)

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        
        try:
            
            cursor.execute("SELECT user_id FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                flash('User with this email already exists.', 'danger')
                return redirect(url_for('admin.manage_accounts'))

            # 6. Insert into main users table using the CUSTOM ID
            cursor.execute("""
                INSERT INTO users (user_id, email, password, role, is_verified) 
                VALUES (%s, %s, %s, %s, %s)
            """, (custom_user_id, email, hashed_password, role, is_verified))

            # 7. Insert into specific profile table based on role
            if role == 'teacher':
                cursor.execute("""
                    INSERT INTO teachers (teacher_id, firstname, middlename, lastname, email, region, province, city, barangay)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (custom_user_id, firstname, middlename, lastname, email, region, province, city, barangay))
            elif role == 'student':
                cursor.execute("""
                    INSERT INTO students (student_id, firstname, middlename, lastname, email, region, province, city, barangay)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (custom_user_id, firstname, middlename, lastname, email, region, province, city, barangay))
            elif role == 'admin':
                cursor.execute("""
                    INSERT INTO admins (admin_id, firstname, middlename, lastname, email, region, province, city, barangay)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (custom_user_id, firstname, middlename, lastname, email, region, province, city, barangay))

            connection.commit()
            flash(f'Account created successfully! ID: {custom_user_id}', 'success')

        except mysql.connector.Error as err:
            connection.rollback()
            flash(f'Database error: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()

        return redirect(url_for('admin.manage_accounts'))

    return render_template('admin_accounts.html')

def generate_id(role_prefix):
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    year_suffix = datetime.now().strftime("%y") 
    like_pattern = f"{role_prefix}{year_suffix}-%"
    cursor.execute("SELECT user_id FROM users WHERE user_id LIKE %s ORDER BY user_id DESC LIMIT 1", (like_pattern,))
    result = cursor.fetchone()
    new_num = (int(result[0].split('-')[1]) + 1) if result else 1
    cursor.close()
    connection.close()
    return f"{role_prefix}{year_suffix}-{str(new_num).zfill(4)}"

@admin.route('/delete_account/<string:user_id>', methods=['POST'])
def delete_account(user_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET is_active = 0 WHERE user_id = %s", (user_id,))
        connection.commit()
        cursor.close()
        connection.close()
        
        flash('Account deleted successfully.', 'success')
        return redirect(url_for('admin.manage_accounts'))
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
    
@admin.route('/restore_account/<string:user_id>', methods=['POST'])
def restore_account(user_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET is_active = 1 WHERE user_id = %s", (user_id,))
        connection.commit()
        cursor.close()
        connection.close()
        
        flash('Account restored successfully.', 'success')
        return redirect(url_for('admin.trashed_accounts'))
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
    
@admin.route('/delete_account_permanently/<string:user_id>', methods=['POST'])
def delete_account_permanently(user_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        connection.commit()
        cursor.close()
        connection.close()
        
        flash('Account deleted successfully.', 'success')
        return redirect(url_for('admin.manage_accounts'))
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))


@admin.route('/empty_trash', methods=['POST'])
def empty_trash():
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("DELETE FROM users WHERE is_active = 0 OR is_active IS NULL")
        connection.commit()
        cursor.close()
        connection.close()
        
        flash('Trash emptied successfully.', 'success')
        return redirect(url_for('admin.trashed_accounts'))


#! MANAGE COURSES
@admin.route('/manage_courses')
def manage_courses():
    if admin_logged_in():
        firstname = session.get('firstname') 
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT c.*, t.firstname AS teacher_fname, t.lastname AS teacher_lname,
            (SELECT COUNT(*) FROM enrollments WHERE course_id = c.course_id) AS student_count
            FROM courses c
            LEFT JOIN teachers t ON c.teacher_id = t.teacher_id
            WHERE c.is_active = 1
            ORDER BY c.course_code ASC
        """)
        courses = cursor.fetchall()
        
        cursor.execute("""
            SELECT t.teacher_id, t.firstname, t.lastname
            FROM teachers t
            INNER JOIN users u ON t.teacher_id = u.user_id
            WHERE u.is_verified = 1
        """)
        
        teachers = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('admin_courses.html', courses=courses, teachers=teachers, firstname=firstname)
    return redirect(url_for('auth.login'))

@admin.route('/add_course', methods=['POST'])
def add_course():
    if not admin_logged_in():
        return redirect(url_for('auth.login'))

    course_code = request.form.get('course_code')
    course_name = request.form.get('course_name')
    description = request.form.get('description')
    teacher_id = request.form.get('teacher_id')

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()

    try:
        # 🔍 Check duplicate by course_code ONLY
        cursor.execute("""
            SELECT course_id FROM courses 
            WHERE course_code = %s
        """, (course_code,))

        if cursor.fetchone():
            flash('Course code already exists. Please use a different code.', 'warning')
            return redirect(url_for('admin.manage_courses'))

        t_id = teacher_id if teacher_id != "" else None

        cursor.execute("""
            INSERT INTO courses (course_code, course_name, description, teacher_id) 
            VALUES (%s, %s, %s, %s)
        """, (course_code, course_name, description, t_id))

        connection.commit()
        flash(f'Course {course_code} added successfully!', 'success')

    except mysql.connector.Error as err:
        flash(f'Error: {err}', 'danger')

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for('admin.manage_courses'))

@admin.route('/update_course/<int:course_id>', methods=['POST'])
def update_course(course_id):
    if not admin_logged_in():
        return redirect(url_for('auth.login'))

    course_code = request.form.get('course_code')
    course_name = request.form.get('course_name')
    description = request.form.get('description')
    teacher_id = request.form.get('teacher_id')

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()

    try:
        # 🔍 Check duplicate code excluding current record
        cursor.execute("""
            SELECT course_id FROM courses 
            WHERE course_code = %s AND course_id != %s
        """, (course_code, course_id))

        if cursor.fetchone():
            flash('Course code already exists. Please use a different code.', 'warning')
            return redirect(url_for('admin.manage_courses'))

        t_id = teacher_id if teacher_id != "" else None

        cursor.execute("""
            UPDATE courses 
            SET course_code = %s, course_name = %s, description = %s, teacher_id = %s 
            WHERE course_id = %s
        """, (course_code, course_name, description, t_id, course_id))

        connection.commit()
        flash('Course updated successfully.', 'success')

    except mysql.connector.Error as err:
        flash(f'Error: {err}', 'danger')

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for('admin.manage_courses'))
@admin.route('/trashed_courses')
def trashed_courses():
    if not admin_logged_in():
        return redirect(url_for('auth.login'))
    trashed_courses = []
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM courses WHERE is_active = 0")
        trashed_courses = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f'Error fetching trashed courses: {err}', 'danger')

    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals() and connection.is_connected():
            connection.close()

    return render_template('admin_trashed_courses.html', trashed_courses=trashed_courses)

@admin.route('/deactivate_course/<int:course_id>', methods=['POST'])
def deactivate_course(course_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("UPDATE courses SET is_active = 0 WHERE course_id = %s", (course_id,))
            cursor.execute("UPDATE courses SET teacher_id = NULL WHERE course_id = %s", (course_id,))
            connection.commit()
            flash('Course deactivated.', 'success')
            
        except mysql.connector.Error as err:
            flash(f'Cannot deactivate course: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()
        return redirect(url_for('admin.manage_courses'))
    return redirect(url_for('auth.login'))

@admin.route('/restore_course/<string:course_code>', methods=['POST'])
def restore_course(course_code):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("UPDATE courses SET is_active = 1 WHERE course_code = %s", (course_code,))
            connection.commit()
            flash('Course restored.', 'success')
        except mysql.connector.Error as err:
            flash(f'Cannot restore course: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()
        return redirect(url_for('admin.manage_courses'))
    return redirect(url_for('auth.login'))

@admin.route('/delete_course_permanently/<string:course_code>', methods=['POST'])
def delete_course_permanently(course_code):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("DELETE FROM courses WHERE course_code = %s", (course_code,))
            connection.commit()
            flash('Course deleted permanently.', 'success')
        except mysql.connector.Error as err:
            flash(f'Cannot delete course: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()
        return redirect(url_for('admin.trashed_courses'))
    return redirect(url_for('auth.login'))

@admin.route('/empty_course_trash', methods=['POST'])
def empty_course_trash():
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("DELETE FROM courses WHERE is_active = 0")
            connection.commit()
            flash('Course trash emptied.', 'success')
        except mysql.connector.Error as err:
            flash(f'Cannot empty course trash: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()
        return redirect(url_for('admin.trashed_courses'))
    return redirect(url_for('auth.login'))

    
#! MANAGE EXAMS

@admin.route('/oversee_exams')
def oversee_exams():
    if admin_logged_in():
        firstname = session.get('firstname')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("""
            SELECT e.exam_id, e.title, c.course_name, e.duration_minutes, e.pass_percentage, e.is_active 
            FROM exams e 
            JOIN courses c ON e.course_id = c.course_id
        """)
        exams = cursor.fetchall()

        cursor.execute("SELECT course_id, course_name FROM courses")
        courses = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('admin_exams.html', exams=exams, courses=courses, firstname=firstname)
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))


@admin.route('/user_logs')
def user_logs():
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT user_id, email, role, created_at
            FROM users
            ORDER BY created_at DESC
        """)

        users = cursor.fetchall()

        for user in users:
            role = (user.get("role") or "").lower()

            user["role_class"] = {
                "admin": "danger",
                "teacher": "primary",
                "student": "success"
            }.get(role, "secondary")

        return render_template('admin_logs.html', user_logs=users)

    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
    
@admin.route('/settings')
def settings():
    if admin_logged_in():
        firstname = session.get('firstname')
        return render_template('admin_settings.html', firstname=firstname)
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
    
#! PROFILE

@admin.route('/profile', methods=['GET', 'POST'])
def profile():
    if not admin_logged_in():
        flash('Please log in as admin to access the profile.', 'danger')
        return redirect(url_for('auth.login'))

    user_id = session.get('user_id')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)

    if request.method == 'POST':
        firstname = request.form.get('firstname')
        middlename = request.form.get('middlename')
        lastname = request.form.get('lastname')
        new_password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        try:
            # Update Admin Table (Name/Profile)
            cursor.execute("""
                UPDATE admins 
                SET firstname = %s, middlename = %s, lastname = %s 
                WHERE admin_id = %s
            """, (firstname, middlename, lastname, user_id))

            # Update Password if provided
            if new_password:
                if new_password == confirm_password:
                    hashed_pw = generate_password_hash(new_password)
                    cursor.execute("UPDATE users SET password = %s WHERE user_id = %s", (hashed_pw, user_id))
                else:
                    flash('Passwords do not match.', 'warning')
                    return redirect(url_for('admin.profile'))

            connection.commit()
            flash('Profile updated successfully.', 'success')
        except mysql.connector.Error as err:
            connection.rollback()
            flash(f'Error: {err}', 'danger')
        
        return redirect(url_for('admin.profile'))

    # GET: Fetch Admin Data
    cursor.execute("""
        SELECT u.user_id, u.email, u.role, u.created_at, 
               a.firstname, a.middlename, a.lastname, 
               a.region, a.province, a.city, a.barangay
        FROM users u
        JOIN admins a ON u.user_id = a.admin_id
        WHERE u.user_id = %s
    """, (user_id,))
    user_data = cursor.fetchone()

    cursor.close()
    connection.close()
    return render_template('admin_profile.html', user=user_data)

#! ENROLLMENT MANAGEMENT (ADMIN)
@admin.route('/manage_enrollments/<int:course_id>')
def manage_enrollments(course_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM courses WHERE course_id = %s", (course_id,))
        course = cursor.fetchone()
        
        cursor.execute("""
            SELECT s.student_id, s.firstname, s.lastname, s.email, e.enrollment_id, e.enrolled_at
            FROM students s
            JOIN enrollments e ON s.student_id = e.student_id
            WHERE e.course_id = %s
        """, (course['course_id'],))
        enrollees = cursor.fetchall()
        
        cursor.execute("""
            SELECT s.student_id, s.firstname, s.lastname
            FROM students s
            INNER JOIN users u ON s.student_id = u.user_id
            LEFT JOIN enrollments e 
                ON s.student_id = e.student_id AND e.course_id = %s
            WHERE u.is_verified = 1
            AND e.student_id IS NULL;
        """, (course['course_id'],))
        
        all_students = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('admin_enrollees.html', course=course, enrollees=enrollees, all_students=all_students)
    return redirect(url_for('auth.login'))

@admin.route('/enroll_student', methods=['POST'])
def enroll_student():
    if admin_logged_in():
        student_id = request.form.get('student_id')
        course_id = request.form.get('course_id')
        
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("INSERT INTO enrollments (student_id, course_id) VALUES (%s, %s)", (student_id, course_id))
            connection.commit()
            flash('Student enrolled successfully!', 'success')
        except mysql.connector.Error:
            flash('Student is already enrolled in this course.', 'warning')
        finally:
            cursor.close()
            connection.close()
        return redirect(url_for('admin.manage_enrollments', course_id=course_id))
    return redirect(url_for('auth.login'))

@admin.route('/unenroll_student/<int:enrollment_id>/<int:course_id>', methods=['POST'])
def unenroll_student(enrollment_id, course_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("DELETE FROM enrollments WHERE enrollment_id = %s", (enrollment_id,))
        connection.commit()
        cursor.close()
        connection.close()
        flash('Student removed from course.', 'success')
        return redirect(url_for('admin.manage_enrollments', course_id=course_id))
    return redirect(url_for('auth.login'))

