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
<body style="margin:0;padding:0;font-family:'Georgia',serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="min-height:100vh;">
    <tr><td align="center" style="padding:48px 16px;">
      <table width="520" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;width:100%;background-color:#16161e;border:1px solid #2a2a38;border-radius:16px;overflow:hidden;">
        <tr><td style="height:4px;background:linear-gradient(90deg,#c9a96e 0%,#e8c98a 50%,#c9a96e 100%);"></td></tr>
        <tr>
          <td align="center" style="padding:40px 48px 32px;">
            <div style="width:52px;height:52px;border-radius:12px;background:linear-gradient(135deg,#c9a96e,#8a6535);margin:0 auto 16px;text-align:center;line-height:52px;font-size:22px;">✦</div>
            <span style="font-family:'Georgia',serif;font-size:11px;letter-spacing:4px;text-transform:uppercase;color:#c9a96e;">Verification Required</span>
          </td>
        </tr>
        <tr><td style="padding:0 48px;"><div style="height:1px;background:linear-gradient(90deg,transparent,#2a2a38,transparent);"></div></td></tr>
        <tr>
          <td style="padding:40px 48px 32px;">
            <p style="margin:0 0 8px;font-size:22px;color:#f0ede8;font-weight:normal;line-height:1.3;">
              Hello, <span style="color:#c9a96e;">{recipient_name}</span>
            </p>
            <p style="margin:0 0 32px;font-size:15px;color:#7a7a8c;line-height:1.7;">
              Use the one-time code below to complete your verification. This code is valid for
              <strong style="color:#a0a0b0;">10 minutes</strong> and should not be shared with anyone.
            </p>
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td align="center" style="padding:32px 0;background-color:#0f0f13;border-radius:12px;border:1px solid #2a2a38;">
                  <p style="margin:0 0 10px;font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#5a5a6e;">Your verification code</p>
                  <p style="margin:0;font-family:'Courier New',monospace;font-size:42px;font-weight:700;letter-spacing:14px;color:#c9a96e;text-indent:14px;">{otp_code}</p>
                </td>
              </tr>
            </table>
            <p style="margin:28px 0 0;font-size:13px;color:#5a5a6e;line-height:1.7;">
              If you did not request this code, you can safely disregard this email.
            </p>
          </td>
        </tr>
        <tr><td style="padding:0 48px;"><div style="height:1px;background:linear-gradient(90deg,transparent,#2a2a38,transparent);"></div></td></tr>
        <tr>
          <td align="center" style="padding:28px 48px 40px;">
            <p style="margin:0 0 6px;font-size:12px;color:#3a3a4a;">Need help? <a href="#" style="color:#c9a96e;text-decoration:none;">Contact Support</a></p>
            <p style="margin:0;font-size:11px;color:#2e2e3a;letter-spacing:1px;">© 2026 · All rights reserved</p>
          </td>
        </tr>
        <tr><td style="height:2px;background:linear-gradient(90deg,transparent,#2a2a38,transparent);"></td></tr>
      </table>
    </td></tr>
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
            query_fetch_student = "SELECT firstname FROM students WHERE email = %s;"
            cursor.execute(query_fetch_student, (email_input,))
            student_data = cursor.fetchone()
            
            session['user_logged_in'] = True
            session['user_id'] = user['user_id']
            cursor.close()
            connection.close()
            return redirect(url_for('student.student_dashboard'))

        elif user['role'] == 'teacher':
            query_fetcch_teacher = "SELECT firstname FROM teachers WHERE email = %s;"
            cursor.execute(query_fetcch_teacher, (email_input,))
            teacher_data = cursor.fetchone()
            session['teacher_logged_in'] = True
            session['user_id'] = user['user_id']
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

@auth.route('/logout', methods=['POST'])
def logout(): 
    session.clear()
    return redirect(url_for('auth.login'))