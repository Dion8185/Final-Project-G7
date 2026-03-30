from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
import mysql.connector
from testpoint import db_config
from testpoint.Auth.login import admin_logged_in

admin = Blueprint('admin', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/admin/static')

@admin.route('/')
def admin_dashboard():
    
    if admin_logged_in():
        return render_template('admin_dashboard.html')
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))


#! MANAGE ACCOUNTS
@admin.route('/manage_accounts' )
def manage_accounts():
    
    if admin_logged_in():
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
    
        return render_template('admin_accounts.html', users=users)
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))

@admin.route('/trashed_accounts')
def trashed_accounts():
    if admin_logged_in():
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
        
        return render_template('admin_trashed.html', trashed_users=trashed_users)
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))

from werkzeug.security import generate_password_hash # Ensure you have this import

@admin.route('/update_account/<string:user_id>', methods=['POST'])
def update_account(user_id):
    if admin_logged_in():
        firstname = request.form.get('firstname')
        middlename = request.form.get('middlename')
        lastname = request.form.get('lastname')
        email = request.form.get('email')
        is_verified = request.form.get('status')
        role = request.form.get('role')
        
        # Password Logic
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
        return render_template('admin_courses.html')
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
    
@admin.route('/oversee_exams')
def oversee_exams():
    if admin_logged_in():
        return render_template('admin_exams.html')
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
    
@admin.route('/user_logs')
def user_logs():
    if admin_logged_in():
        return render_template('admin_logs.html')
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
    
@admin.route('/settings')
def settings():
    if admin_logged_in():
        return render_template('admin_settings.html')
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
    
