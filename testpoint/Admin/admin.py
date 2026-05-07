from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
import mysql.connector
from testpoint import db_config
from testpoint.Auth.login import admin_logged_in
from werkzeug.security import generate_password_hash
from testpoint import email as SENDER_EMAIL
from testpoint import db_config, mail
from flask_mail import Message
import os

admin = Blueprint('admin', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/admin/static')

UPLOAD_FOLDER = 'testpoint/static/uploads/verifications'
ALLOWED_EXTENSIONS = {'pdf'}

@admin.route('/admin_dashboard')
def admin_dashboard():
    print(f"DEBUG: Current User Role is {session.get('role')}")
    if admin_logged_in():
        firstname = session.get('firstname')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        try:
            # 1. Main Summary Stats
            cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_active = 1")
            total_users = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM programs WHERE is_active = 1")
            total_programs = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM blocks WHERE is_active = 1")
            total_blocks = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM classes WHERE is_active = 1")
            total_classes = cursor.fetchone()['count']

            # 2. Live Data
            cursor.execute("SELECT COUNT(*) as count FROM exam_attempts WHERE status = 'in-progress'")
            live_sessions = cursor.fetchone()['count']

            cursor.execute("SELECT SUM(tab_switches) as total FROM exam_attempts")
            global_violations = cursor.fetchone()['total'] or 0

            # 3. Pie Chart: User Distribution
            cursor.execute("SELECT role, COUNT(*) as count FROM users WHERE is_active = 1 GROUP BY role")
            role_data = cursor.fetchall()
            pie_labels = [r['role'].capitalize() for r in role_data]
            pie_values = [r['count'] for r in role_data]

            # 4. Bar Chart: Year Level Distribution (Derived from block names like '1A', '2B')
            cursor.execute("""
                SELECT LEFT(block_name, 1) as year, COUNT(s.student_id) as count 
                FROM blocks b
                JOIN students s ON b.block_id = s.block_id
                WHERE b.is_active = 1
                GROUP BY year ORDER BY year
            """)
            year_data = cursor.fetchall()
            year_labels = [f"Year {y['year']}" for y in year_data]
            year_values = [y['count'] for y in year_data]

            cursor.execute("""
                SELECT 
                    b.block_id,      -- ADD THIS LINE
                    b.block_name, 
                    p.program_name, 
                    b.capacity, 
                    (SELECT COUNT(*) FROM students WHERE block_id = b.block_id) as current_count
                FROM blocks b
                JOIN programs p ON b.program_id = p.program_id
                WHERE b.is_active = 1
                HAVING (current_count / b.capacity) >= 0.8
                ORDER BY (current_count / b.capacity) DESC 
                LIMIT 5
            """)
            watchlist = cursor.fetchall()

        finally:
            cursor.close(); connection.close()

        return render_template('admin_dashboard.html', 
                               firstname=firstname,
                               total_users=total_users,
                               total_programs=total_programs,
                               total_blocks=total_blocks,
                               total_classes=total_classes,
                               live_sessions=live_sessions,
                               global_violations=global_violations,
                               pie_labels=pie_labels,
                               pie_values=pie_values,
                               year_labels=year_labels,
                               year_values=year_values,
                               watchlist=watchlist)
    return redirect(url_for('auth.login'))


#! 1. MANAGE ACCOUNTS (Modified to handle Blocks)
@admin.route('/manage_accounts')
def manage_accounts():
    if admin_logged_in():    
        firstname = session.get('firstname')  
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
    
        cursor.execute(""" SELECT 
                            u.user_id,
                            u.is_active,
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
                            WHERE u.is_active IN (1);
        """)
        users = cursor.fetchall()
        
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
        firstname = request.form.get('firstname')
        lastname = request.form.get('lastname')
        middlename = request.form.get('middlename')
        email = request.form.get('email')
        is_active = request.form.get('is_active') 
        role = request.form.get('role')
        block_id = request.form.get('block_id')
        new_password = request.form.get('password')

        if role in ['admin', 'super_admin']:
            is_active = 1

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            # Update the core users table
            if new_password:
                hashed_pw = generate_password_hash(new_password)
                cursor.execute("""
                    UPDATE users 
                    SET email = %s, is_active = %s, password = %s 
                    WHERE user_id = %s
                """, (email, is_active, hashed_pw, user_id))
            else:
                cursor.execute("""
                    UPDATE users 
                    SET email = %s, is_active = %s 
                    WHERE user_id = %s
                """, (email, is_active, user_id))

            # Update specific profile info based on role
            if role == 'teacher':
                cursor.execute("""
                    UPDATE teachers 
                    SET firstname = %s, middlename = %s, lastname = %s 
                    WHERE teacher_id = %s
                """, (firstname, middlename, lastname, user_id))
                
            elif role == 'student':
                b_id = block_id if block_id and block_id.strip() != "" else None
                cursor.execute("""
                    UPDATE students 
                    SET firstname = %s, middlename = %s, lastname = %s, block_id = %s 
                    WHERE student_id = %s
                """, (firstname, middlename, lastname, b_id, user_id))
                
            elif role == 'admin' or role == 'super_admin':
                cursor.execute("""
                    UPDATE admins 
                    SET firstname = %s, middlename = %s, lastname = %s 
                    WHERE admin_id = %s
                """, (firstname, middlename, lastname, user_id))
            
            connection.commit()
            
            # Specific flash message if an attempt to deactivate an admin was blocked
            if request.form.get('is_active') == '0' and role in ['admin', 'super_admin']:
                flash('Account info updated, but Administrative accounts cannot be deactivated.', 'warning')
            else:
                flash('Account updated successfully.', 'success')

        except mysql.connector.Error as err:
            connection.rollback()
            flash(f'Database Error: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()
            
        return redirect(url_for('admin.manage_accounts'))
    
    return redirect(url_for('auth.login'))

@admin.route('/add_user', methods=['GET', 'POST'])
def add_user():
    if not admin_logged_in(): 
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        fname = request.form.get('firstname')
        mname = request.form.get('middlename')
        lname = request.form.get('lastname')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'student').lower()
        block_id = request.form.get('block_id')

        region = request.form.get('region_text')
        province = request.form.get('province_text')
        city = request.form.get('city_text')
        barangay = request.form.get('barangay_text')

        prefix = {'admin': 'A', 'teacher': 'T', 'student': 'S'}.get(role, 'U')
        custom_user_id = generate_id(prefix)
        hashed_password = generate_password_hash(password)

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()

        try:
            cursor.execute("SELECT user_id FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                flash('User with this email already exists.', 'danger')
                return redirect(url_for('admin.manage_accounts'))

            cursor.execute("""
                INSERT INTO users (user_id, email, password, role, is_verified, is_active) 
                VALUES (%s, %s, %s, %s, 1, 1)
            """, (custom_user_id, email, hashed_password, role))

            if role == 'teacher':
                cursor.execute("""
                    INSERT INTO teachers (teacher_id, email, firstname, middlename, lastname, region, province, city, barangay) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (custom_user_id, email, fname, mname, lname, region, province, city, barangay))

            elif role == 'student':
                b_id = block_id if block_id and block_id.strip() != "" else None
                cursor.execute("""
                    INSERT INTO students (student_id, email, firstname, middlename, lastname, block_id, region, province, city, barangay) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (custom_user_id, email, fname, mname, lname, b_id, region, province, city, barangay))

            elif role == 'admin' or role == 'super_admin':
                cursor.execute("""
                    INSERT INTO admins (admin_id, email, firstname, middlename, lastname, region, province, city, barangay) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (custom_user_id, email, fname, mname, lname, region, province, city, barangay))

            connection.commit()
            flash(f'Account created successfully! User ID is {custom_user_id}', 'success')

        except mysql.connector.Error as err:
            connection.rollback()
            flash(f'Database Error: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()

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
        if session.get('role') != 'super_admin':
            flash('Unauthorized action.', 'danger')
            return redirect(url_for('admin.admin_dashboard'))

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
    
    cursor.execute("SELECT * FROM programs WHERE is_active = 1 ORDER BY program_name")
    progs = cursor.fetchall()
    cursor.close(); connection.close()
    return render_template('admin_programs.html', programs=progs, firstname=session.get('firstname'))

@admin.route('/view_program_blocks/<int:program_id>')
def view_program_blocks(program_id):
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM programs WHERE program_id = %s", (program_id,))
    program = cursor.fetchone()
    
    if not program:
        flash("Program not found.", "danger")
        return redirect(url_for('admin.manage_programs'))

    cursor.execute("""
        SELECT b.*, 
        (SELECT COUNT(*) FROM students WHERE block_id = b.block_id) as current_count
        FROM blocks b 
        WHERE b.program_id = %s AND b.is_active = 1
    """, (program_id,))
    blocks = cursor.fetchall()
    
    cursor.close(); connection.close()
    return render_template('admin_program_blocks_view.html', 
                           program=program, 
                           blocks=blocks, 
                           firstname=session.get('firstname'))

@admin.route('/edit_program/<int:program_id>', methods=['POST'])
def edit_program(program_id):
    if admin_logged_in():
        name = request.form.get('program_name')
        desc = request.form.get('description')
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        try:
            cursor.execute("UPDATE programs SET program_name = %s, description = %s WHERE program_id = %s", (name, desc, program_id))
            connection.commit()
            flash(f'Program "{name}" updated.', 'success')
        finally:
            cursor.close(); connection.close()
        return redirect(url_for('admin.manage_programs'))
    return redirect(url_for('auth.login'))

@admin.route('/archive_program/<int:program_id>', methods=['POST'])
def archive_program(program_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("UPDATE programs SET is_active = 0 WHERE program_id = %s", (program_id,))
        connection.commit(); cursor.close(); connection.close()
        flash('Program moved to trash.', 'warning')
        return redirect(url_for('admin.manage_programs'))
    return redirect(url_for('auth.login'))

@admin.route('/trashed_programs')
def trashed_programs():
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM programs WHERE is_active = 0")
        trashed = cursor.fetchall()
        cursor.close(); connection.close()
        return render_template('admin_trashed_programs.html', trashed_programs=trashed, firstname=session.get('firstname'))
    return redirect(url_for('auth.login'))

@admin.route('/restore_program/<int:program_id>', methods=['POST'])
def restore_program(program_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("UPDATE programs SET is_active = 1 WHERE program_id = %s", (program_id,))
        connection.commit(); cursor.close(); connection.close()
        flash('Program restored successfully.', 'success')
        return redirect(url_for('admin.trashed_programs'))
    return redirect(url_for('auth.login'))

@admin.route('/delete_program_permanently/<int:program_id>', methods=['POST'])
def delete_program_permanently(program_id):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        try:
            cursor.execute("DELETE FROM programs WHERE program_id = %s", (program_id,))
            connection.commit()
            flash('Program deleted permanently.', 'danger')
        except mysql.connector.Error as err:
            flash(f'Database Error: {err}', 'danger')
        finally:
            cursor.close(); connection.close()
        return redirect(url_for('admin.trashed_programs'))
    return redirect(url_for('auth.login'))

# ! 3. MANAGE BLOCKS & SECTIONS
@admin.route('/manage_blocks', methods=['GET', 'POST'])
def manage_blocks():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    
    if request.method == 'POST':
        p_id = request.form.get('program_id')
        year_level = request.form.get('year_level')
        cap = request.form.get('capacity')
        
        try:
            # 1. Find all existing blocks for this program & year
            cursor.execute("""
                SELECT block_name FROM blocks 
                WHERE program_id = %s AND block_name LIKE %s AND is_active = 1
                ORDER BY block_name
            """, (p_id, f"{year_level}%"))
            existing_blocks = [b['block_name'] for b in cursor.fetchall()] # List of block names
            
            # 2. Generate Next Block Name
            if not existing_blocks:
                # No blocks, start at A
                new_block_name = f"{year_level}A"
            else:
                # Extract the letters
                letters = [block_name[1:] for block_name in existing_blocks]
                
                # Find the next letter (handle wrap-around)
                last_letter = letters[-1] #Get the most recent added
                next_letter = chr(ord(last_letter) + 1)
                new_block_name = f"{year_level}{next_letter}"

            # 3. Insert the New Block
            cursor.execute("""
                INSERT INTO blocks (program_id, block_name, capacity, is_active) 
                VALUES (%s, %s, %s, 1)
            """, (p_id, new_block_name, cap))
            connection.commit()
            flash(f"Created Block: {new_block_name}", "success")

        except mysql.connector.Error as err:
            flash(f"Error creating block: {err}", "danger")
        return redirect(url_for('admin.manage_blocks'))
    
    # GET Method: Fetch active blocks with current count
    cursor.execute("""
        SELECT b.*, p.program_name, 
        (SELECT COUNT(*) FROM students WHERE block_id = b.block_id) as current_count
        FROM blocks b 
        JOIN programs p ON b.program_id = p.program_id
        WHERE b.is_active = 1
    """)
    blks = cursor.fetchall()
    
    # Fetch active programs for dropdown
    cursor.execute("SELECT * FROM programs WHERE is_active = 1")
    progs = cursor.fetchall()
    
    cursor.close(); connection.close()
    return render_template('admin_blocks.html', blocks=blks, programs=progs, firstname=session.get('firstname'))

@admin.route('/edit_block/<int:block_id>', methods=['POST'])
def edit_block(block_id):
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    new_name = request.form.get('block_name')
    new_cap = int(request.form.get('capacity'))
    
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    try:
        # Prevent setting capacity lower than current student count
        cursor.execute("SELECT COUNT(*) as count FROM students WHERE block_id = %s", (block_id,))
        current_count = cursor.fetchone()['count']
        
        if new_cap < current_count:
            flash(f"Invalid Capacity: Block already has {current_count} students. Cannot reduce limit to {new_cap}.", "danger")
        else:
            cursor.execute("UPDATE blocks SET block_name = %s, capacity = %s WHERE block_id = %s", (new_name, new_cap, block_id))
            connection.commit()
            flash("Block updated successfully.", "success")
    finally:
        cursor.close(); connection.close()
    return redirect(url_for('admin.manage_blocks'))


@admin.route('/archive_block/<int:block_id>', methods=['POST'])
def archive_block(block_id):
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    cursor.execute("UPDATE blocks SET is_active = 0 WHERE block_id = %s", (block_id,))
    connection.commit(); cursor.close(); connection.close()
    flash('Block moved to trash.', 'warning')
    return redirect(url_for('admin.manage_blocks'))


@admin.route('/trashed_blocks')
def trashed_blocks():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    cursor.execute("""
        SELECT b.*, p.program_name 
        FROM blocks b 
        JOIN programs p ON b.program_id = p.program_id 
        WHERE b.is_active = 0
    """)
    trashed = cursor.fetchall()
    cursor.close(); connection.close()
    return render_template('admin_trashed_blocks.html', trashed_blocks=trashed, firstname=session.get('firstname'))


@admin.route('/restore_block/<int:block_id>', methods=['POST'])
def restore_block(block_id):
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    cursor.execute("UPDATE blocks SET is_active = 1 WHERE block_id = %s", (block_id,))
    connection.commit(); cursor.close(); connection.close()
    flash('Block restored to active list.', 'success')
    return redirect(url_for('admin.trashed_blocks'))


@admin.route('/delete_block_permanently/<int:block_id>', methods=['POST'])
def delete_block_permanently(block_id): # <--- Ensure this name is exactly this
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM blocks WHERE block_id = %s", (block_id,))
        connection.commit()
        flash('Block permanently deleted.', 'danger')
    except mysql.connector.Error as err:
        flash(f"Error: {err}", "danger")
    finally:
        cursor.close(); connection.close()
    return redirect(url_for('admin.trashed_blocks'))


# --- BLOCK STUDENT ENROLLMENT LOGIC ---

@admin.route('/manage_block_students/<int:block_id>')
def manage_block_students(block_id):
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    
    # Fetch Block & Capacity Info
    cursor.execute("""
        SELECT b.*, p.program_name 
        FROM blocks b 
        JOIN programs p ON b.program_id = p.program_id 
        WHERE b.block_id = %s
    """, (block_id,))
    block_info = cursor.fetchone()

    # Fetch Students currently in this block
    cursor.execute("SELECT student_id, firstname, lastname, email FROM students WHERE block_id = %s", (block_id,))
    current_students = cursor.fetchall()

    # Fetch Unassigned Students (Verified and Active)
    cursor.execute("""
        SELECT s.student_id, s.firstname, s.lastname 
        FROM students s
        JOIN users u ON s.student_id = u.user_id
        WHERE s.block_id IS NULL AND u.is_verified = 1 AND u.is_active = 1
    """)
    unassigned_students = cursor.fetchall()

    cursor.close(); connection.close()
    return render_template('admin_block_students.html', 
                           block=block_info, 
                           students=current_students, 
                           unassigned=unassigned_students,
                           firstname=session.get('firstname'))


@admin.route('/assign_to_block', methods=['POST'])
def assign_to_block():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    block_id = request.form.get('block_id')
    student_ids = request.form.getlist('student_ids')
    
    if not student_ids:
        flash("No students selected.", "warning")
        return redirect(url_for('admin.manage_block_students', block_id=block_id))

    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    try:
        # Validate capacity before updating
        cursor.execute("""
            SELECT capacity, (SELECT COUNT(*) FROM students WHERE block_id = b.block_id) as current_count 
            FROM blocks b WHERE block_id = %s
        """, (block_id,))
        block_stats = cursor.fetchone()
        
        available_slots = block_stats['capacity'] - block_stats['current_count']
        
        if len(student_ids) > available_slots:
            flash(f"Overcapacity: Only {available_slots} slots available, but you selected {len(student_ids)} students.", "danger")
        else:
            format_strings = ','.join(['%s'] * len(student_ids))
            cursor.execute(f"UPDATE students SET block_id = %s WHERE student_id IN ({format_strings})", [block_id] + student_ids)
            connection.commit()
            flash(f"Successfully assigned {len(student_ids)} students.", "success")
    finally:
        cursor.close(); connection.close()
    return redirect(url_for('admin.manage_block_students', block_id=block_id))


@admin.route('/remove_from_block/<string:student_id>/<int:block_id>', methods=['POST'])
def remove_from_block(student_id, block_id):
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    cursor.execute("UPDATE students SET block_id = NULL WHERE student_id = %s", (student_id,))
    connection.commit(); cursor.close(); connection.close()
    flash("Student removed from block.", "info")
    return redirect(url_for('admin.manage_block_students', block_id=block_id))


@admin.route('/bulk_remove_from_block', methods=['POST'])
def bulk_remove_from_block():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    block_id = request.form.get('block_id')
    student_ids = request.form.getlist('student_ids')
    
    if not student_ids:
        flash("No students selected for removal.", "warning")
        return redirect(url_for('admin.manage_block_students', block_id=block_id))
    
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    try:
        format_strings = ','.join(['%s'] * len(student_ids))
        cursor.execute(f"UPDATE students SET block_id = NULL WHERE student_id IN ({format_strings})", tuple(student_ids))
        connection.commit()
        flash(f"Removed {len(student_ids)} students from block.", "info")
    finally:
        cursor.close(); connection.close()
    return redirect(url_for('admin.manage_block_students', block_id=block_id))

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
        # We no longer request 'course_code' from the form
        name = request.form.get('course_name')
        desc = request.form.get('description')
        
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            # We ONLY update name and description. The code stays the same.
            cursor.execute("""
                UPDATE courses 
                SET course_name = %s, description = %s 
                WHERE course_code = %s
            """, (name, desc, old_code))
            
            connection.commit()
            flash(f'Subject {old_code} updated successfully.', 'success')
        except mysql.connector.Error as err:
            flash(f'Error: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()
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
        co_code = request.form.get('course_code')
        b_id = request.form.get('block_id')
        t_id = request.form.get('teacher_id')
        
        try:
            # 1. DUPLICATION CHECK (Fixes the Anomaly)
            # Check if this specific Block is already assigned this Course in an active class
            cursor.execute("""
                SELECT class_code FROM classes 
                WHERE course_code = %s AND block_id = %s AND is_active = 1
            """, (co_code, b_id))
            
            duplicate = cursor.fetchone()
            if duplicate:
                # EXPLICIT DISALLOWED MESSAGE
                flash(f"Action Disallowed: This block is already scheduled for this subject in Class {duplicate['class_code']}. Duplicate sessions for the same block are not permitted.", "warning")
                return redirect(url_for('admin.manage_classes'))

            # 2. AUTO-GENERATE CLASS CODE (#101, #102...)
            cursor.execute("SELECT class_code FROM classes WHERE class_code LIKE '#%'")
            all_codes = cursor.fetchall()
            
            highest_num = 0
            for row in all_codes:
                try:
                    # Strip the '#' and convert the remaining string to an integer
                    num = int(row['class_code'][1:])
                    if num > highest_num: highest_num = num
                except (ValueError, IndexError):
                    continue
            
            # Start at #101 if no classes exist, otherwise increment
            new_code_val = 101 if highest_num == 0 else highest_num + 1
            new_class_code = f"#{new_code_val}"

            # 3. DATABASE INSERTION
            cursor.execute("""
                INSERT INTO classes (class_code, course_code, block_id, teacher_id, is_active) 
                VALUES (%s, %s, %s, %s, 1)
            """, (new_class_code, co_code, b_id, t_id))
            
            connection.commit()
            flash(f"Successfully scheduled {new_class_code} for this block.", "success")

        except mysql.connector.Error as err:
            flash(f"Database Error: {err}", "danger")
        finally:
            cursor.close(); connection.close()
        return redirect(url_for('admin.manage_classes'))

    # --- GET LOGIC: Fetch Data for the Table and Dropdowns ---
    try:
        # Fetch current active classes for the table view
        cursor.execute("""
            SELECT cl.*, c.course_name, b.block_name, p.program_name, t.firstname, t.lastname
            FROM classes cl
            JOIN courses c ON cl.course_code = c.course_code
            JOIN blocks b ON cl.block_id = b.block_id
            JOIN programs p ON b.program_id = p.program_id
            LEFT JOIN teachers t ON cl.teacher_id = t.teacher_id
            WHERE cl.is_active = 1
        """)
        classes_data = cursor.fetchall()
        
        # Fetch active Subjects (Catalog) for dropdown
        cursor.execute("SELECT course_code, course_name FROM courses WHERE is_active = 1 ORDER BY course_name")
        subjects = cursor.fetchall()
        
        # Fetch active Blocks for dropdown
        cursor.execute("""
            SELECT b.block_id, b.block_name, p.program_name 
            FROM blocks b 
            JOIN programs p ON b.program_id = p.program_id 
            WHERE b.is_active = 1
            ORDER BY p.program_name, b.block_name
        """)
        blocks_data = cursor.fetchall()
        
        # Fetch all Teachers for dropdown
        cursor.execute("SELECT teacher_id, firstname, lastname FROM teachers ORDER BY lastname")
        teachers = cursor.fetchall()

    finally:
        cursor.close(); connection.close()

    return render_template('admin_classes.html', 
                           classes=classes_data, 
                           subjects=subjects, 
                           blocks=blocks_data, 
                           teachers=teachers, 
                           firstname=session.get('firstname'))

@admin.route('/archive_class/<string:class_code>', methods=['POST'])
def archive_class(class_code):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("UPDATE classes SET is_active = 0 WHERE class_code = %s", (class_code,))
        connection.commit(); cursor.close(); connection.close()
        flash(f'Class {class_code} moved to trash.', 'warning')
    return redirect(url_for('admin.manage_classes'))

@admin.route('/trashed_classes')
def trashed_classes():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    cursor.execute("""
        SELECT cl.*, c.course_name, b.block_name, p.program_name 
        FROM classes cl
        JOIN courses c ON cl.course_code = c.course_code
        JOIN blocks b ON cl.block_id = b.block_id
        JOIN programs p ON b.program_id = p.program_id
        WHERE cl.is_active = 0
    """)
    trashed = cursor.fetchall(); cursor.close(); connection.close()
    return render_template('admin_trashed_classes.html', trashed_classes=trashed, firstname=session.get('firstname'))

@admin.route('/restore_class/<string:class_code>', methods=['POST'])
def restore_class(class_code):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("UPDATE classes SET is_active = 1 WHERE class_code = %s", (class_code,))
        connection.commit(); cursor.close(); connection.close()
        flash(f'Class {class_code} restored.', 'success')
    return redirect(url_for('admin.trashed_classes'))

@admin.route('/delete_class_permanently/<string:class_code>', methods=['POST'])
def delete_class_permanently(class_code):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("DELETE FROM classes WHERE class_code = %s", (class_code,))
        connection.commit(); cursor.close(); connection.close()
        flash(f'Class {class_code} deleted permanently.', 'danger')
    return redirect(url_for('admin.trashed_classes'))

#! 6. BULK ENROLLMENT (By Block)
@admin.route('/enroll_block', methods=['POST'])
def enroll_block():
    if not admin_logged_in(): 
        return redirect(url_for('auth.login'))
        
    class_code = request.form.get('class_code')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    try:
        # Get target class and its course_code
        cursor.execute("SELECT block_id, course_code FROM classes WHERE class_code = %s", (class_code,))
        class_info = cursor.fetchone()
        
        if class_info:
            # Insert students from the block ONLY if they are not already enrolled 
            # in any class that has the same course_code
            cursor.execute("""
                INSERT INTO enrollments (student_id, class_code)
                SELECT s.student_id, %s 
                FROM students s
                WHERE s.block_id = %s
                AND NOT EXISTS (
                    SELECT 1 FROM enrollments e
                    JOIN classes cl ON e.class_code = cl.class_code
                    WHERE e.student_id = s.student_id 
                    AND cl.course_code = %s
                )
            """, (class_code, class_info['block_id'], class_info['course_code']))
            
            enrolled_count = cursor.rowcount
            connection.commit()
            
            if enrolled_count > 0:
                flash(f"Processed block enrollment. {enrolled_count} students added to {class_code}.", "success")
            else:
                flash("No students were added. All students in this block are already enrolled in this course.", "info")
                
    except mysql.connector.Error as err:
        connection.rollback()
        flash(f"Error during bulk enrollment: {err}", "danger")
    finally:
        cursor.close()
        connection.close()
        
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


#! 10. PROFILE (Enhanced for Command Center Data)
@admin.route('/profile', methods=['GET', 'POST'])
def profile():
    if not admin_logged_in(): 
        return redirect(url_for('auth.login'))
        
    user_id = session.get('user_id')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)

    try:
        if request.method == 'POST':
            fname = request.form.get('firstname')
            mname = request.form.get('middlename')
            lname = request.form.get('lastname')
            new_pw = request.form.get('password')
            conf_pw = request.form.get('confirm_password')

            cursor.execute("""
                UPDATE admins 
                SET firstname = %s, middlename = %s, lastname = %s 
                WHERE admin_id = %s
            """, (fname, mname, lname, user_id))

            if new_pw:
                if new_pw == conf_pw:
                    cursor.execute("UPDATE users SET password = %s WHERE user_id = %s", 
                                   (generate_password_hash(new_pw), user_id))
                else:
                    flash('Passwords do not match.', 'warning')
                    return redirect(url_for('admin.profile'))

            connection.commit()
            flash('Admin profile updated successfully.', 'success')
            return redirect(url_for('admin.profile'))

        # --- GET: FETCH DETAILED ADMIN DATA & SYSTEM STATS ---
        cursor.execute("""
            SELECT u.*, a.* 
            FROM users u 
            JOIN admins a ON u.user_id = a.admin_id 
            WHERE u.user_id = %s
        """, (user_id,))
        user_data = cursor.fetchone()

        # Fetch Global Counts for the Profile Dashboard
        cursor.execute("SELECT COUNT(*) as count FROM students")
        total_students = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM teachers")
        total_teachers = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM pending_users WHERE verification_status = 'pending_approval'")
        pending_tasks = cursor.fetchone()['count']

        return render_template('admin_profile.html', 
                               user=user_data, 
                               total_students=total_students, 
                               total_teachers=total_teachers,
                               pending_tasks=pending_tasks)

    finally:
        cursor.close()
        connection.close()


#! 11. ENROLLMENT MANAGEMENT
#! 11. ENROLLMENT MANAGEMENT - REFINED FILTERING
@admin.route('/manage_enrollments/<path:class_code>')
def manage_enrollments(class_code):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        try:
            # 1. Fetch current class info and its associated course_code
            cursor.execute("""
                SELECT cl.*, c.course_name, c.course_code 
                FROM classes cl 
                JOIN courses c ON cl.course_code = c.course_code 
                WHERE cl.class_code = %s
            """, (class_code,))
            class_info = cursor.fetchone()
            
            if not class_info:
                flash("Class not found.", "danger")
                return redirect(url_for('admin.manage_classes'))

            # 2. Fetch students currently enrolled in THIS specific class
            cursor.execute("""
                SELECT s.student_id, s.firstname, s.lastname, s.email, e.enrollment_id, e.enrolled_at
                FROM students s
                JOIN enrollments e ON s.student_id = e.student_id
                WHERE e.class_code = %s
                ORDER BY s.lastname ASC
            """, (class_code,))
            enrollees = cursor.fetchall()

            # 3. Fetch "Verified Students" for the dropdown
            # RULE: Exclude students who are already enrolled in ANY class that shares this same course_code
            cursor.execute("""
                SELECT s.student_id, s.firstname, s.lastname
                FROM students s
                JOIN users u ON s.student_id = u.user_id
                WHERE u.is_verified = 1 
                AND u.is_active = 1
                AND s.student_id NOT IN (
                    SELECT e.student_id 
                    FROM enrollments e
                    JOIN classes cl ON e.class_code = cl.class_code
                    WHERE cl.course_code = %s
                )
                ORDER BY s.lastname ASC
            """, (class_info['course_code'],))
            all_students = cursor.fetchall()

            return render_template('admin_enrollees.html', 
                                   class_info=class_info, 
                                   enrollees=enrollees, 
                                   all_students=all_students)
        finally:
            cursor.close()
            connection.close()
            
    return redirect(url_for('auth.login'))

@admin.route('/enroll_student', methods=['POST'])
def enroll_student():
    if not admin_logged_in():
        return redirect(url_for('auth.login'))
        
    student_id = request.form.get('student_id')
    class_code = request.form.get('class_code')
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    try:
        # 1. Get the course_code for the class we are trying to enroll them in
        cursor.execute("SELECT course_code FROM classes WHERE class_code = %s", (class_code,))
        target_class = cursor.fetchone()
        
        if not target_class:
            flash('Invalid class selection.', 'danger')
            return redirect(url_for('admin.manage_classes'))
            
        course_code = target_class['course_code']

        # 2. Check if the student is already enrolled in ANY class with this same course_code
        cursor.execute("""
            SELECT e.class_code 
            FROM enrollments e
            JOIN classes cl ON e.class_code = cl.class_code
            WHERE e.student_id = %s AND cl.course_code = %s
        """, (student_id, course_code))
        
        existing_enrollment = cursor.fetchone()

        if existing_enrollment:
            flash(f'Student is already enrolled in this course via Class {existing_enrollment["class_code"]}.', 'warning')
        else:
            # 3. Proceed with enrollment if no duplicate course found
            cursor.execute("INSERT INTO enrollments (student_id, class_code) VALUES (%s, %s)", (student_id, class_code))
            connection.commit()
            flash('Student successfully enrolled.', 'success')
            
    except mysql.connector.Error as err:
        connection.rollback()
        flash(f'Database Error: {err}', 'danger')
    finally:
        cursor.close()
        connection.close()
        
    return redirect(url_for('admin.manage_enrollments', class_code=class_code))

@admin.route('/unenroll_student/<int:enrollment_id>/<path:class_code>', methods=['POST'])
def unenroll_student(enrollment_id, class_code):
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            # The <path:> converter is used instead of <string:> to better handle 
            # characters that might be part of the encoded string.
            cursor.execute("DELETE FROM enrollments WHERE enrollment_id = %s", (enrollment_id,))
            connection.commit()
            flash('Student successfully unenrolled.', 'success')
        except mysql.connector.Error as err:
            flash(f'Database Error: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()
            
        return redirect(url_for('admin.manage_enrollments', class_code=class_code))
    return redirect(url_for('auth.login'))

#! 12. VERIFICATIONS
@admin.route('/verifications')
def view_verifications():
    if not admin_logged_in(): return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM pending_users ORDER BY created_at DESC")
    pending_list = cursor.fetchall()
    
    cursor.close()
    connection.close()
    return render_template('admin_verifications.html', pending_list=pending_list, firstname=session.get('firstname'))


#!  ADMIN APPROVAL
@admin.route('/approve_user/<int:pending_id>', methods=['POST'])
def approve_user(pending_id):
    if not admin_logged_in(): return jsonify({"error": "Unauthorized"}), 403
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM pending_users WHERE pending_id = %s", (pending_id,))
    p = cursor.fetchone()
    
    if p:
        new_id = generate_id('S' if p['role'] == 'student' else 'T')
        
        if p['document_path']:
                file_path = os.path.join(UPLOAD_FOLDER, p['document_path'])
                if os.path.exists(file_path): os.remove(file_path)

        try:
            cursor.execute("INSERT INTO users (user_id, email, password, role, is_verified) VALUES (%s, %s, %s, %s, 1)", 
                           (new_id, p['email'], p['password'], p['role']))
            
            if p['role'] == 'student':
                # Explicitly setting block_id to NULL to trigger post-approval setup
                cursor.execute("""
                    INSERT INTO students (student_id, email, firstname, lastname, middlename, block_id, region, province, city, barangay) 
                    VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s, %s)
                """, (new_id, p['email'], p['firstname'], p['lastname'], p['middlename'], p['region'], p['province'], p['city'], p['barangay']))
            else:
                cursor.execute("INSERT INTO teachers (teacher_id, email, firstname, lastname, middlename, region, province, city, barangay) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", 
                               (new_id, p['email'], p['firstname'], p['lastname'], p['middlename'], p['region'], p['province'], p['city'], p['barangay']))
            
            cursor.execute("DELETE FROM pending_users WHERE pending_id = %s", (pending_id,))
            
            # --- STRUCTURED EMAIL ---
            msg = Message(
                subject='Account Approved - TestPoint',
                sender=("TestPoint", SENDER_EMAIL),
                recipients=[p['email']]
            )
            msg.html = f"""
            <body
    style="margin:0;padding:0;font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f7f9fc;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="padding: 50px 15px;">
        <tr>
            <td align="center">
                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                    style="max-width: 500px; background-color: #ffffff; border: 1px solid #e1e7ef; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
                    <tr>
                        <td style="height: 6px; background-color: #2d58d1; border-radius: 12px 12px 0 0;"></td>
                    </tr>
                    <tr>
                        <td align="center" style="padding: 40px 40px 20px;">
                            <h1 style="font-size: 42px; margin:0;">📑</h1>
                            <div
                                style="font-size: 11px; letter-spacing: 3px; text-transform: uppercase; color: #2d58d1; font-weight: bold; margin-top: 10px;">
                                TestPoint Examination System</div>
                        </td>
                    </tr>
                    <tr>
                        <td style="text-align: justify; padding: 0 40px 40px;">
                            <p style="margin: 0 0 10px; font-size: 20px; color: #1a1a1a;">Hello
                                <strong>{p['firstname']}</strong>,</p>
                            <p style="margin: 0 0 30px; font-size: 15px; color: #5e6d7a; line-height: 1.6;">Your
                                registration has been reviewed and <strong>approved</strong>. You can now access the
                                system using the email and password you used during registration.</p>
                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                style="background-color: #f0f7ff; border: 1px solid #dbeafe; border-radius: 8px;">
                                <tr>
                                    <td align="center" style="padding: 25px;">
                                        <p
                                            style="margin: 0 0 10px; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: #1e40af; opacity: 0.7;">
                                            Your User ID:</p>
                                        <p
                                            style="margin: 0; font-family: 'Courier New', monospace; font-size: 35px; font-weight: 700; color: #1e40af;">
                                            {new_id}</p>
                                    </td>
                                </tr>
                            </table>
                            <p
                                style="margin: 30px 0 0; font-size: 13px; color: #94a3b8; line-height: 1.5; text-align: center;">
                                Please keep your credentials secure.</p>
                        </td>
                    </tr>
                    <tr>
                        <td align="center"
                            style="padding: 25px 40px; border-top: 1px solid #f1f5f9; background-color: #f8fafc; border-radius: 0 0 12px 12px;">
                            <p style="margin: 0; font-size: 11px; color: #94a3b8;">© TestPoint 2026 · All rights
                                reserved</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>"""
            mail.send(msg)
            connection.commit()
            return jsonify({"message": "User approved"}), 200
        except Exception as e: 
            connection.rollback()
            return jsonify({"error": str(e)}), 500
        finally: 
            cursor.close()
            connection.close()
    return jsonify({"error": "Not found"}), 404

#!  ADMIN ACTION: REJECT USER (PERMANENT)
@admin.route('/reject_user/<int:pending_id>', methods=['POST'])
def reject_user(pending_id):
    if not admin_logged_in(): return jsonify({"error": "Unauthorized"}), 403
    reason = request.form.get('reason')
    notes = request.form.get('notes')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT email, firstname, document_path FROM pending_users WHERE pending_id = %s", (pending_id,))
    p = cursor.fetchone()

    if p:
        try:
            if p['document_path']:
                file_path = os.path.join(UPLOAD_FOLDER, p['document_path'])
                if os.path.exists(file_path): os.remove(file_path)

            # --- STRUCTURED EMAIL ---
            msg = Message(
                subject='Registration Rejected - TestPoint',
                sender=("TestPoint", SENDER_EMAIL),
                recipients=[p['email']]
            )
            msg.html = f"""
            <body style="margin:0;padding:0;font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f7f9fc;">
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="padding: 50px 15px;">
                    <tr><td align="center"><table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width: 500px; background-color: #ffffff; border: 1px solid #e1e7ef; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
                        <tr><td style="height: 6px; background-color: #dc2626; border-radius: 12px 12px 0 0;"></td></tr>
                        <tr><td align="center" style="padding: 40px 40px 20px;"><h1 style="font-size: 42px; margin:0;">📑</h1><div style="font-size: 11px; letter-spacing: 3px; text-transform: uppercase; color: #dc2626; font-weight: bold; margin-top: 10px;">TestPoint Examination System</div></td></tr>
                        <tr><td style="text-align: justify; padding: 0 40px 40px;">
                            <p style="margin: 0 0 10px; font-size: 20px; color: #1a1a1a;">Hello <strong>{p['firstname']}</strong>,</p>
                            <p style="margin: 0 0 30px; font-size: 15px; color: #5e6d7a; line-height: 1.6;">Unfortunately, your registration application has been <strong>rejected</strong> by our administrative team.</p>
                            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #fef2f2; border: 1px solid #fecaca; border-radius: 8px;">
                                <tr><td style="padding: 20px;"><p style="margin: 0 0 5px; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: #991b1b; opacity: 0.7;">Rejection Details</p>
                                <p style="margin: 0; font-size: 15px; color: #991b1b;"><strong>Reason:</strong> {reason}</p>
                                <p style="margin: 5px 0 0; font-size: 14px; color: #991b1b; opacity: 0.8;">{notes}</p></td></tr>
                            </table>
                            <p style="margin: 30px 0 0; font-size: 13px; color: #94a3b8; line-height: 1.5; text-align: center;">If you believe this was a mistake, please register again with accurate information.</p>
                        </td></tr>
                        <tr><td align="center" style="padding: 25px 40px; border-top: 1px solid #f1f5f9; background-color: #f8fafc; border-radius: 0 0 12px 12px;"><p style="margin: 0; font-size: 11px; color: #94a3b8;">© TestPoint 2026 · All rights reserved</p></td></tr>
                    </table></td></tr>
                </table>
            </body>"""
            mail.send(msg)
            cursor.execute("DELETE FROM pending_users WHERE pending_id = %s", (pending_id,))
            connection.commit()
            return jsonify({"message": "Rejected"}), 200
        except Exception as e: 
            connection.rollback()
            return jsonify({"error": str(e)}), 500
        finally: 
            cursor.close()
            connection.close()
    return jsonify({"error": "User not found"}), 404

#! ADMIN ACTION: REQUEST RESUBMISSION
@admin.route('/resubmit_user/<int:pending_id>', methods=['POST'])
def resubmit_user(pending_id):
    if not admin_logged_in(): return jsonify({"error": "Unauthorized"}), 403
    reason = request.form.get('reason')
    notes = request.form.get('notes')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT email, firstname, document_path FROM pending_users WHERE pending_id = %s", (pending_id,))
    p = cursor.fetchone()

    if p:
        try:
            if p['document_path']:
                file_path = os.path.join(UPLOAD_FOLDER, p['document_path'])
                if os.path.exists(file_path): os.remove(file_path)

            full_note = f"Reason: {reason}. {notes}"
            cursor.execute("UPDATE pending_users SET verification_status = 'pending_upload', document_path = NULL, admin_notes = %s WHERE pending_id = %s", (full_note, pending_id))

            # --- STRUCTURED EMAIL ---
            msg = Message(
                subject='Resubmit Documents - TestPoint',
                sender=("TestPoint", SENDER_EMAIL),
                recipients=[p['email']]
            )
            msg.html = f"""
            <body style="margin:0;padding:0;font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f7f9fc;">
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="padding: 50px 15px;">
                    <tr><td align="center"><table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width: 500px; background-color: #ffffff; border: 1px solid #e1e7ef; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
                        <tr><td style="height: 6px; background-color: #f59e0b; border-radius: 12px 12px 0 0;"></td></tr>
                        <tr><td align="center" style="padding: 40px 40px 20px;"><h1 style="font-size: 42px; margin:0;">📑</h1><div style="font-size: 11px; letter-spacing: 3px; text-transform: uppercase; color: #f59e0b; font-weight: bold; margin-top: 10px;">TestPoint Examination System</div></td></tr>
                        <tr><td style="text-align: justify; padding: 0 40px 40px;">
                            <p style="margin: 0 0 10px; font-size: 20px; color: #1a1a1a;">Hello <strong>{p['firstname']}</strong>,</p>
                            <p style="margin: 0 0 30px; font-size: 15px; color: #5e6d7a; line-height: 1.6;">Our admins have reviewed your registration and require a <strong>new document upload</strong> to proceed.</p>
                            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #fffbeb; border: 1px solid #fef3c7; border-radius: 8px;">
                                <tr><td style="padding: 20px;"><p style="margin: 0 0 5px; font-size: 11px; letter-spacing: 1px; text-transform: uppercase; color: #92400e; opacity: 0.7;">Admin Feedback</p>
                                <p style="margin: 0; font-size: 15px; color: #92400e; font-style: italic;">"{full_note}"</p></td></tr>
                            </table>
                            <p style="margin: 30px 0 0; font-size: 13px; color: #94a3b8; line-height: 1.5; text-align: center;">Please log in to your account and upload the correct PDF file.</p>
                        </td></tr>
                        <tr><td align="center" style="padding: 25px 40px; border-top: 1px solid #f1f5f9; background-color: #f8fafc; border-radius: 0 0 12px 12px;"><p style="margin: 0; font-size: 11px; color: #94a3b8;">© TestPoint 2026 · All rights reserved</p></td></tr>
                    </table></td></tr>
                </table>
            </body>"""
            mail.send(msg)
            connection.commit()
            return jsonify({"message": "Resubmission requested"}), 200
        except Exception as e: 
            connection.rollback()
            return jsonify({"error": str(e)}), 500
        finally: 
            cursor.close()
            connection.close()
    return jsonify({"error": "User not found"}), 404