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

def user_logged_in(): 
    return session.get('user_logged_in', False)
def admin_logged_in(): 
    return session.get('admin_logged_in', False)
def teacher_logged_in(): 
    return session.get('teacher_logged_in', False)

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
        msg = Message(subject='Test Point - Account Verification Code', sender='verify@gmail.com', recipients=[recipient_email])
        msg.html = f"""
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Verification Code</title>
</head>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.3/css/all.min.css" />

<body style="margin:0;padding:0;font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f7f9fc;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="padding: 50px 15px;">
        <tr>
            <td align="center">
                <!-- Main Card -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                    style="max-width: 500px; background-color: #ffffff; border: 1px solid #e1e7ef; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">

                    <!-- Blue Top Bar -->
                    <tr>
                        <td style="height: 6px; background-color: #2d58d1; border-radius: 12px 12px 0 0;"></td>
                    </tr>

                    <!-- Header -->
                    <tr>
                        <td align="center" style="padding: 40px 40px 20px;">
                            <h1 style="font-size: 42px;">📑</i></h1>
                            <div style="font-size: 11px; letter-spacing: 3px; text-transform: uppercase; color: #2d58d1; font-weight: bold; margin-top: 10px;">
                                TestPoint Examination System
                            </div>
                        </td>
                    </tr>

                    <!-- Body Content -->
                    <tr>
                        <td style="padding: 0 40px 40px;">
                            <p style="margin: 0 0 10px; font-size: 20px; color: #1a1a1a; font-weight: normal;">
                                Hello, <span style="color: #2d58d1; font-weight: 600;">{recipient_name}</span>
                            </p>

                            <p style="margin: 0 0 30px; font-size: 15px; color: #5e6d7a; line-height: 1.6;">
                                Use the one-time code below to complete your verification. This code is valid for
                                <strong style="color: #333;">10 minutes</strong> and should not be shared with anyone.
                            </p>

                            <!-- OTP Code Box (Updated to Blue Theme) -->
                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                style="background-color: #f0f7ff; border: 1px solid #dbeafe; border-radius: 8px;">
                                <tr>
                                    <td align="center" style="padding: 25px;">
                                        <p style="margin: 0 0 10px; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: #1e40af; opacity: 0.7;">
                                            Your verification code
                                        </p>
                                        <p style="margin: 0; font-family: 'Courier New', monospace; font-size: 40px; font-weight: 700; letter-spacing: 12px; color: #1e40af; text-indent: 12px;">
                                            {otp_code}
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 30px 0 0; font-size: 13px; color: #94a3b8; line-height: 1.5; text-align: center;">
                                If you did not request this code, you can safely disregard this email.
                            </p>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td align="center" style="padding: 25px 40px; border-top: 1px solid #f1f5f9; background-color: #f8fafc; border-radius: 0 0 12px 12px;">
                            <p style="margin: 0 0 6px; font-size: 12px; color: #64748b;">
                                Need help? <a href="#" style="color: #2d58d1; text-decoration: none; font-weight: 600;">Contact Support</a>
                            </p>
                            <p style="margin: 0; font-size: 11px; color: #94a3b8; letter-spacing: 1px;">
                                © 2026 · All rights reserved
                            </p>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>
</body>

</html>
"""
    
        mail.send(msg)
        print("📧 Generated OTP for account: " + otp_code)
    except Exception as e:
        print(f"Error sending email: {e}")


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
    
        if user['is_verified'] == 0:
            cursor.execute("SELECT firstname, lastname FROM students WHERE email = %s", (email_input,))
            student_data = cursor.fetchone()
            fname = student_data['firstname'] if student_data else "User"
            lname = student_data['lastname'] if student_data else ""
            session['pending_user_id'] = user['user_id']
            session['email'] = user['email']
            session['firstname'] = fname
            session['lastname'] = lname
            
            cursor.close()
            connection.close()
            flash('Your account is not verified yet. Please verify your email.', 'warning')
            return redirect(url_for('auth.verify_register'))

        if user['role'] == 'admin' and (user['password'] == password_input or check_password_hash(user['password'], password_input)):
            query_fetch_admin = "SELECT firstname FROM admins WHERE email = %s;"
            cursor.execute(query_fetch_admin, (email_input,))
            admin_data = cursor.fetchone()

            session['admin_logged_in'] = True
            session['user_id'] = user['user_id']
            session['email'] = user['email']
            session['firstname'] = admin_data['firstname']
            cursor.close()
            connection.close()
            return redirect(url_for('admin.admin_dashboard'))
        
        if not check_password_hash(user['password'], password_input):
            cursor.close()
            connection.close()
            flash('Invalid username or password!', 'danger')
            return render_template('login.html')

        elif user['role'] == 'student':
            query_fetch_student = "SELECT firstname, lastname FROM students WHERE email = %s;"
            cursor.execute(query_fetch_student, (email_input,))
            student_data = cursor.fetchone()
            
            session['user_logged_in'] = True
            session['user_id'] = user['user_id']
            session['email'] = user['email']
            session['role'] = 'student'

            if student_data:
                session['firstname'] = student_data['firstname']
                session['lastname'] = student_data['lastname']
            cursor.close()
            connection.close()
            return redirect(url_for('student.student_dashboard'))

        elif user['role'] == 'teacher':
            query_fetch_teacher = "SELECT firstname, lastname FROM teachers WHERE email = %s;"
            cursor.execute(query_fetch_teacher, (email_input,))
            teacher_data = cursor.fetchone()
            session['teacher_logged_in'] = True
            session['user_id'] = user['user_id']
            session['email'] = user['email']
            session['role'] = 'teacher'
            
            if teacher_data:
                session['firstname'] = teacher_data.get('firstname', '')
                session['lastname'] = teacher_data.get('lastname', '')
            cursor.close()
            connection.close()
            return redirect(url_for('teacher.teacher_dashboard'))

    return render_template('login.html')

@auth.route('/register/student', methods=['GET', 'POST'])
def register_student():
    if user_logged_in():
        return redirect(url_for('student.student_dashboard'))
    
    if admin_logged_in():
        return redirect(url_for('admin.admin_dashboard'))
    
    if teacher_logged_in():
        return redirect(url_for('teacher.teacher_dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        fname = request.form.get('firstname')
        lname = request.form.get('lastname')
        mname = request.form.get('middlename')
        password = request.form.get('password')
        
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            if existing_user['is_verified'] == 0:
                session['pending_user_id'] = existing_user['user_id']
                session['email'] = email
                session['firstname'] = fname
                flash("This email is already registered but unverified. Redirecting to verification.", "info")
                return redirect(url_for('auth.verify_register'))
            else:
                flash("Email already in use. Please log in.", "danger")
                return render_template('register.html')

        hashed_pw = generate_password_hash(password)
        student_id = generate_id('S')

        try:
            cursor.execute("INSERT INTO users (user_id, email, password, role, is_verified) VALUES (%s, %s, %s, 'student', 0)", 
                           (student_id, email, hashed_pw))
            
            cursor.execute("INSERT INTO students (student_id, email, firstname, lastname, middlename, region, province, city, barangay) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                           (student_id, email, fname, lname, mname, request.form.get('region_text'), request.form.get('province_text'), request.form.get('city_text'), request.form.get('barangay_text')))

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

@auth.route('/register/teacher', methods=['GET', 'POST'])
def register_teacher():
    if user_logged_in():
        return redirect(url_for('student.student_dashboard'))
    
    if admin_logged_in():
        return redirect(url_for('admin.admin_dashboard'))
    
    if teacher_logged_in():
        return redirect(url_for('teacher.teacher_dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        fname = request.form.get('firstname')
        lname = request.form.get('lastname')
        mname = request.form.get('middlename')
        password = request.form.get('password')
        
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        
        if existing_user:
           
            if existing_user['is_verified'] == 0:
                session['pending_user_id'] = existing_user['user_id']
                session['email'] = email
                session['firstname'] = fname
                flash("This email is already registered but unverified. Redirecting to verification.", "info")
                return redirect(url_for('auth.verify_register'))
            else:
                flash("Email already in use. Please log in.", "danger")
                return render_template('register_teacher.html')


        hashed_pw = generate_password_hash(password)
        teacher_id = generate_id('T')

        try:
            cursor.execute("INSERT INTO users (user_id, email, password, role, is_verified) VALUES (%s, %s, %s, 'teacher', 0)", 
                           (teacher_id, email, hashed_pw))
            
            cursor.execute("INSERT INTO teachers (teacher_id, email, firstname, lastname, middlename, region, province, city, barangay) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                           (teacher_id, email, fname, lname, mname, request.form.get('region_text'), request.form.get('province_text'), request.form.get('city_text'), request.form.get('barangay_text')))

            otp = generate_unique_otp()
            expires = datetime.now() + timedelta(minutes=10)
            cursor.execute("INSERT INTO otp_table (user_id, otp_code, expires_at) VALUES (%s, %s, %s)", (teacher_id, otp, expires))
            
            connection.commit()
            send_otp_email(email, fname, otp)
            
            session['pending_user_id'] = teacher_id
            session['email'] = email
            session['firstname'] = fname
            
            return redirect(url_for('auth.verify_register'))
        
        except Exception as e:
            connection.rollback()
            flash(f"Error: {str(e)}", "danger")
        finally:
            cursor.close()
            connection.close()
            
    return render_template('register_teacher.html')

@auth.route('/verify_register', methods=['GET', 'POST'])
def verify_register():
    
    user_id = session.get('pending_user_id')
    if not user_id:
        flash("No pending registration found. Please register or log in.", "warning")
        return redirect(url_for('auth.login'))

    ConnectionAbortedError 
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
        
        cursor.execute("UPDATE otp_table SET is_used = 1 WHERE user_id = %s", (user_id,))
        
        cursor.execute("INSERT INTO otp_table (user_id, otp_code, expires_at) VALUES (%s, %s, %s)", (user_id, otp, expires))
        connection.commit()
        cursor.close()
        connection.close()
        
        send_otp_email(email, fname, otp)
        return jsonify({"message": "New code sent!"}), 200
    return jsonify({"message": "Session expired."}), 400

@auth.route('/logout', methods=['POST', 'GET'])
def logout():
    user_id = session.get('user_id')
    active_exam_id = session.get('active_exam_id')

    if active_exam_id and user_id:
        print(f"DEBUG: Student {user_id} is logging out during Exam {active_exam_id}. Auto-submitting...")
        
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True, buffered=True) 
        
        try:
            # 1. Find the attempt
            cursor.execute("""
                SELECT attempt_id FROM exam_attempts 
                WHERE student_id = %s AND exam_id = %s AND status = 'in-progress'
                ORDER BY start_time DESC LIMIT 1
            """, (user_id, active_exam_id))
            attempt = cursor.fetchone()

            if attempt:
                attempt_id = attempt['attempt_id']
                
                # 2. Get list of questions
                cursor.execute("SELECT question_id FROM exam_questions WHERE exam_id = %s", (active_exam_id,))
                questions = cursor.fetchall()
                
                total_score = 0
                for q in questions:
                    q_id = q['question_id']
                    
                    # Fetch student's last answer
                    cursor.execute("SELECT submitted_answer FROM student_answers WHERE attempt_id = %s AND question_id = %s", (attempt_id, q_id))
                    ans_row = cursor.fetchone()
                    
                    # Fetch the correct option
                    cursor.execute("SELECT option_text FROM options WHERE question_id = %s AND is_correct = 1", (q_id,))
                    corr_row = cursor.fetchone()

                    if ans_row and corr_row:
                        if str(ans_row['submitted_answer']).strip().lower() == str(corr_row['option_text']).strip().lower():
                            total_score += 1
                            # Mark as correct in DB
                            cursor.execute("UPDATE student_answers SET is_correct = 1 WHERE attempt_id = %s AND question_id = %s", (attempt_id, q_id))

                # 3. Update attempt status to finished
                cursor.execute("""
                    UPDATE exam_attempts SET status = 'finished', end_time = NOW(), score = %s 
                    WHERE attempt_id = %s
                """, (total_score, attempt_id))
                
                connection.commit()
                print(f"DEBUG: Exam {active_exam_id} auto-submitted with score {total_score}")

        except Exception as e:
            print(f"ERROR during auto-submit: {e}")
            if connection:
                connection.rollback()
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                cursor.close()
                
    session.clear()
    return redirect(url_for('auth.login'))