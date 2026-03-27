import random
import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from testpoint import db_config, mail
import mysql.connector
from datetime import datetime, timedelta
from flask_mail import Message

auth = Blueprint('auth', __name__, template_folder='templates', static_folder='static', 
                 static_url_path='/auth/static')

# --- HELPERS ---
def user_logged_in(): return session.get('user_logged_in', False)
def admin_logged_in(): return session.get('admin_logged_in', False)
def teacher_logged_in(): return session.get('teacher_logged_in', False)

NAME_REGEX = re.compile(r"^[A-Za-zñÑ]+([ '-][A-Za-zñÑ]+)*$") 
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

def validate_name(field_name, value):
    value = value.strip()
    if not value or not NAME_REGEX.match(value) or re.search(r'(.)\1{3,}', value):
        flash(f'Invalid {field_name}.', 'danger')
        return False
    return True

def validate_email(email):
    if not email or ' ' in email or not EMAIL_REGEX.match(email):
        flash('Invalid email address.', 'danger')
        return False
    return True

# --- ID & OTP GENERATION ---

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

def generate_unique_otp():
    """Generates a random 6-digit OTP."""
    return str(random.randint(100000, 999999))

def send_otp_email(recipient_email, recipient_name, otp_code):
    try:
        msg = Message(subject='Account Verification Code', sender='verify@gmail.com', recipients=[recipient_email])
        msg.html = f"<h3>Hello {recipient_name},</h3><p>Your 6-digit verification code is: <b>{otp_code}</b></p>"
        mail.send(msg)
    except Exception as e:
        print(f"Error sending email: {e}")

# --- ROUTES ---

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if user_logged_in():
        return redirect(url_for('student.student_dashboard'))
    if admin_logged_in():
        return redirect(url_for('admin.admin_dashboard'))
    if teacher_logged_in():
        return redirect(url_for('teacher.teacher_dashboard'))
    
    if request.method == 'POST':
        email_input = request.form['email']
        password_input = request.form['password']
        
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        query_fetch_user = "SELECT * FROM users WHERE email = %s;"
        cursor.execute(query_fetch_user, (email_input,))
        user = cursor.fetchone()

        if not user:
            cursor.close()
            connection.close()
            flash('Invalid email or password!', 'danger')
            return render_template('login.html')
        
        # 1. CHECK IF UNVERIFIED: Redirect to OTP screen even if they just try to log in
        if user['is_verified'] == 0:
            # Fetch name for the session/email
            cursor.execute("SELECT firstname FROM students WHERE email = %s", (email_input,))
            student_data = cursor.fetchone()
            fname = student_data['firstname'] if student_data else "User"
            
            session['pending_user_id'] = user['user_id']
            session['email'] = user['email']
            session['firstname'] = fname
            
            cursor.close()
            connection.close()
            flash('Your account is not verified yet. Please verify your email.', 'warning')
            return redirect(url_for('auth.verify_register'))

        # 2. PROCEED WITH NORMAL LOGIN FOR VERIFIED USERS
        if user['role'] == 'admin' and (user['password'] == password_input or check_password_hash(user['password'], password_input)):
            session['admin_logged_in'] = True
            cursor.close()
            connection.close()
            return redirect(url_for('admin.admin_dashboard'))
        
        if not check_password_hash(user['password'], password_input):
            cursor.close()
            connection.close()
            flash('Invalid username or password!', 'danger')
            return render_template('login.html')

        elif user['role'] == 'student':
            session['user_logged_in'] = True
            cursor.close()
            connection.close()
            return redirect(url_for('student.student_dashboard'))

        elif user['role'] == 'teacher':
            session['teacher_logged_in'] = True
            cursor.close()
            connection.close()
            return redirect(url_for('teacher.teacher_dashboard'))

    return render_template('login.html')

@auth.route('/register/student', methods=['GET', 'POST'])
def register_student():
    if request.method == 'POST':
        email = request.form.get('email')
        fname = request.form.get('firstname')
        lname = request.form.get('lastname')
        password = request.form.get('password')
        
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            # If exists but not verified, redirect to verification instead of error
            if existing_user['is_verified'] == 0:
                session['pending_user_id'] = existing_user['user_id']
                session['email'] = email
                session['firstname'] = fname
                flash("This email is already registered but unverified. Redirecting to verification.", "info")
                return redirect(url_for('auth.verify_register'))
            else:
                flash("Email already in use. Please log in.", "danger")
                return render_template('register.html')

        # 2. PROCEED WITH NEW REGISTRATION
        hashed_pw = generate_password_hash(password)
        student_id = generate_id('S')

        try:
            cursor.execute("INSERT INTO users (user_id, email, password, role, is_verified) VALUES (%s, %s, %s, 'student', 0)", 
                           (student_id, email, hashed_pw))
            
            cursor.execute("INSERT INTO students (student_id, email, firstname, lastname, region, province, city, barangay) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                           (student_id, email, fname, lname, request.form.get('region_text'), request.form.get('province_text'), request.form.get('city_text'), request.form.get('barangay_text')))

            otp = generate_unique_otp()
            expires = datetime.now() + timedelta(minutes=10)
            cursor.execute("INSERT INTO otp_table (user_id, otp_code, expires_at) VALUES (%s, %s, %s)", (student_id, otp, expires))
            
            connection.commit()
            send_otp_email(email, fname, otp)
            
            session['pending_user_id'] = student_id
            session['email'] = email
            session['firstname'] = fname
            
            return redirect(url_for('auth.verify_register'))
        
        except Exception as e:
            connection.rollback()
            flash(f"Error: {str(e)}", "danger")
        finally:
            cursor.close()
            connection.close()
            
    return render_template('register.html')

@auth.route('/verify_register', methods=['GET', 'POST'])
def verify_register():
    user_id = session.get('pending_user_id')
    if not user_id:
        flash("No pending registration found. Please register or log in.", "warning")
        return redirect(url_for('auth.login'))

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()

    if request.method == 'POST':
        pin_submitted = "".join([request.form.get(f'pin{i}', '') for i in range(1, 7)]).strip()

        cursor.execute("""
            SELECT otp_code, expires_at 
            FROM otp_table 
            WHERE user_id = %s AND is_used = 0 
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()

        if result:
            db_otp, expires_at = result
            
            if datetime.now() > expires_at:
                flash("The verification code has expired. Please request a new one.", "danger")
            elif pin_submitted == db_otp:
                try:
                    cursor.execute("UPDATE users SET is_verified = 1 WHERE user_id = %s", (user_id,))
                    cursor.execute("UPDATE otp_table SET is_used = 1 WHERE user_id = %s", (user_id,))
                    connection.commit()
                    
                    session.pop('pending_user_id', None)
                    session.pop('email', None)
                    session.pop('firstname', None)

                    flash("Account verified successfully! You can now log in.", "success")
                    return redirect(url_for('auth.login'))
                except mysql.connector.Error as err:
                    connection.rollback()
                    flash(f"Database error: {err}", "danger")
            else:
                flash("Invalid verification code.", "danger")
        else:
            flash("No active code found. Please resend.", "danger")

    cursor.execute("SELECT expires_at FROM otp_table WHERE user_id = %s AND is_used = 0 ORDER BY created_at DESC LIMIT 1", (user_id,))
    timer_result = cursor.fetchone()
    remaining_seconds = max(0, int((timer_result[0] - datetime.now()).total_seconds())) if timer_result else 0

    cursor.close()
    connection.close()
    return render_template('verify.html', remaining_seconds=remaining_seconds)

@auth.route('/resend_otp', methods=['POST'])
def resend_otp():
    user_id = session.get('pending_user_id')
    email = session.get('email')
    fname = session.get('firstname', 'User')

    if user_id and email:
        otp = generate_unique_otp()
        expires = datetime.now() + timedelta(minutes=10)
        
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        # Invalidate old codes
        cursor.execute("UPDATE otp_table SET is_used = 1 WHERE user_id = %s", (user_id,))
        # Insert new code
        cursor.execute("INSERT INTO otp_table (user_id, otp_code, expires_at) VALUES (%s, %s, %s)", (user_id, otp, expires))
        connection.commit()
        cursor.close()
        connection.close()
        
        send_otp_email(email, fname, otp)
        return jsonify({"message": "New code sent!"}), 200
    return jsonify({"message": "Session expired."}), 400

@auth.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))