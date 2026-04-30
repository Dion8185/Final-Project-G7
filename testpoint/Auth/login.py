import random
import string
import re
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from testpoint import db_config, mail
import mysql.connector
from datetime import datetime, timedelta
from flask_mail import Message

auth = Blueprint('auth', __name__, template_folder='templates', static_folder='static', 
                 static_url_path='/auth/static')

# ── CONFIGURATION ──
UPLOAD_FOLDER = 'testpoint/static/uploads/verifications'
ALLOWED_EXTENSIONS = {'pdf'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ── LOGGED IN CHECKS ──
def user_logged_in(): 
    return session.get('user_logged_in', False)
def admin_logged_in(): 
    return session.get('admin_logged_in', False)
def teacher_logged_in(): 
    return session.get('teacher_logged_in', False)
def pending_user_logged_in(): 
    return session.get('pending_user_logged_in', False)

# ── VALIDATION LOGIC ──
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

# ── UTILITY FUNCTIONS ──
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
    return str(random.randint(100000, 999999))

def send_otp_email(recipient_email, recipient_name, otp_code):
    try:
        msg = Message(subject='Test Point - Account Verification Code', sender='verify@testpoint.com', recipients=[recipient_email])
        msg.html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Verification Code</title>
</head>
<body style="margin:0;padding:0;font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f7f9fc;">
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
                            <div style="font-size: 11px; letter-spacing: 3px; text-transform: uppercase; color: #2d58d1; font-weight: bold; margin-top: 10px;">
                                TestPoint Examination System
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td style="text-align: justify; padding: 0 40px 40px;">
                            <p style="margin: 0 0 10px; font-size: 20px; color: #1a1a1a; font-weight: normal;">
                                Hello, <span style="color: #2d58d1; font-weight: 600;">{recipient_name}</span>
                            </p>
                            <p style="margin: 0 0 30px; font-size: 15px; color: #5e6d7a; line-height: 1.6;">
                                Use the one-time code below to complete your verification. This code is valid for
                                <strong style="color: #333;">10 minutes</strong> and should not be shared with anyone.
                            </p>
                            
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
                    <tr>
                        <td align="center" style="padding: 25px 40px; border-top: 1px solid #f1f5f9; background-color: #f8fafc; border-radius: 0 0 12px 12px;">
                            <p style="margin: 0; font-size: 11px; color: #94a3b8; letter-spacing: 1px;">
                                © TestPoint 2026 · All rights reserved
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
        print(f"📑:{otp_code}")
    except Exception as e:
        print(f"Error sending email: {e}")

def send_reset_otp_email(recipient_email, otp_code):
    try:
        msg = Message(subject='Test Point - Password Reset', sender='verify@testpoint.com', recipients=[recipient_email])
        msg.html = f"""
<!DOCTYPE html> 
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Verification Code</title>
</head>
<body style="margin:0;padding:0;font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f7f9fc;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="padding: 50px 15px;">
        <tr>
            <td align="center">
                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                    style="max-width: 500px; background-color: #ffffff; border: 1px solid #e1e7ef; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
                    <tr>
                        <td style="height: 6px; background-color: #dc2626; border-radius: 12px 12px 0 0;"></td>
                    </tr>
                    <tr>
                        <td align="center" style="padding: 40px 40px 20px;">
                            <h1 style="font-size: 42px; margin:0;">📑</h1>
                            <div style="font-size: 11px; letter-spacing: 3px; text-transform: uppercase; color: #dc2626; font-weight: bold; margin-top: 10px;">
                                TestPoint Examination System
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td style="text-align: justify; padding: 0 40px 40px;">
                            <p style="margin: 0 0 30px; font-size: 15px; color: #5e6d7a; line-height: 1.6;"> 
                                Hello <strong>{recipient_email}</strong>, Use the one-time code below to reset your password. This code is valid for
                                <strong style="color: #333;">10 minutes</strong> and should not be shared with anyone.
                            </p>
                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                style="background-color: #fef2f2; border: 1px solid #fecaca; border-radius: 8px;">
                                <tr>
                                    <td align="center" style="padding: 25px;">
                                        <p style="margin: 0 0 10px; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: #991b1b; opacity: 0.7;">
                                            Your verification code
                                        </p>
                                        <p style="margin: 0; font-family: 'Courier New', monospace; font-size: 40px; font-weight: 700; letter-spacing: 12px; color: #991b1b; text-indent: 12px;">
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
                    <tr>
                        <td align="center" style="padding: 25px 40px; border-top: 1px solid #f1f5f9; background-color: #f8fafc; border-radius: 0 0 12px 12px;">
                            <p style="margin: 0; font-size: 11px; color: #94a3b8; letter-spacing: 1px;">
                                © TestPoint 2026 · All rights reserved
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
        mail.send(msg)
        print(f"📑:{otp_code}")
    except Exception as e:
        print(f"Error sending email: {e}")     

#! 1. LOGIN ROUTE
@auth.route('/login', methods=['GET', 'POST'])
def login():
    
    if session.get('in_reset_flow'):
        if not session.get('otp_verified'):
            return redirect(url_for('auth.verify_reset_otp'))
        return redirect(url_for('auth.reset_password'))
    if pending_user_logged_in():
        return redirect(url_for('auth.upload_verification'))
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

        # A. Check Active Users Table
        cursor.execute("SELECT * FROM users WHERE email = %s AND is_active = 1", (email_input,))
        user = cursor.fetchone()

        if user and check_password_hash(user['password'], password_input):
            if user['role'] == 'admin':
                cursor.execute("SELECT firstname FROM admins WHERE email = %s", (email_input,))
                admin_data = cursor.fetchone()
                session.update({'admin_logged_in': True, 'user_id': user['user_id'], 'email': user['email'], 'firstname': admin_data['firstname'], 'role': 'admin'})
                cursor.close(); connection.close(); return redirect(url_for('admin.admin_dashboard'))
            elif user['role'] == 'student':
                cursor.execute("SELECT firstname, lastname FROM students WHERE email = %s", (email_input,))
                s_data = cursor.fetchone()
                session.update({'user_logged_in': True, 'user_id': user['user_id'], 'email': user['email'], 'role': 'student', 'firstname': s_data['firstname'], 'lastname': s_data['lastname']})
                cursor.close(); connection.close(); return redirect(url_for('student.student_dashboard'))
            elif user['role'] == 'teacher':
                cursor.execute("SELECT firstname, lastname FROM teachers WHERE email = %s", (email_input,))
                t_data = cursor.fetchone()
                session.update({'teacher_logged_in': True, 'user_id': user['user_id'], 'email': user['email'], 'role': 'teacher', 'firstname': t_data['firstname'], 'lastname': t_data['lastname']})
                cursor.close(); connection.close(); return redirect(url_for('teacher.teacher_dashboard'))

        # B. Check Pending Users Table
        cursor.execute("SELECT * FROM pending_users WHERE email = %s", (email_input,))
        pending = cursor.fetchone()

        if pending and check_password_hash(pending['password'], password_input):
            session['pending_email'] = pending['email']
            session['pending_role'] = pending['role']
            session['firstname'] = pending['firstname']
            session['pending_user_logged_in'] = True
            
            if not pending['is_otp_verified']:
                flash('Please verify your email OTP.', 'warning')
                cursor.close(); connection.close(); 
                return redirect(url_for('auth.verify_register'))
            
            if pending['verification_status'] == 'pending_upload' or pending['verification_status'] == 'rejected':
                flash('Please upload verification documents.', 'info')
                cursor.close(); connection.close(); 
                return redirect(url_for('auth.upload_verification'))
            
            if pending['verification_status'] == 'pending_approval':
                cursor.close(); connection.close(); 
                return render_template('waiting_approval.html', role=pending['role'])

        flash('Invalid email or password!', 'danger')
        cursor.close(); connection.close()

    return render_template('login.html')

#! 2. REGISTER STUDENT
@auth.route('/register/student', methods=['GET', 'POST'])
def register_student():
    if request.method == 'POST':
        email = request.form.get('email'); fname = request.form.get('firstname'); lname = request.form.get('lastname'); password = request.form.get('password')
        if not (validate_name('First Name', fname) and validate_name('Last Name', lname) and validate_email(email)):
            return render_template('register.html')

        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT email COLLATE utf8mb4_general_ci FROM users WHERE email = %s 
            UNION 
            SELECT email COLLATE utf8mb4_general_ci FROM pending_users WHERE email = %s
        """, (email, email))
        
        if cursor.fetchone():
            flash("Email already in use.", "danger"); return render_template('register.html')

        hashed_pw = generate_password_hash(password); otp = generate_unique_otp(); expiry = datetime.now() + timedelta(minutes=10)
        try:
            cursor.execute("""
                INSERT INTO pending_users (email, password, role, firstname, lastname, middlename, region, province, city, barangay, otp_code, otp_expires_at) 
                VALUES (%s, %s, 'student', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (email, hashed_pw, fname, lname, request.form.get('middlename'), request.form.get('region_text'), request.form.get('province_text'), request.form.get('city_text'), request.form.get('barangay_text'), otp, expiry))
            connection.commit(); send_otp_email(email, fname, otp); session['pending_email'] = email; session['firstname'] = fname; session['pending_role'] = 'student'
            return redirect(url_for('auth.verify_register'))
        except Exception as e:
            connection.rollback(); flash(f"Error: {e}", "danger")
        finally:
            cursor.close(); connection.close()
    return render_template('register.html')

#! 3. REGISTER TEACHER
@auth.route('/register/teacher', methods=['GET', 'POST'])
def register_teacher():
    if request.method == 'POST':
        email = request.form.get('email'); fname = request.form.get('firstname'); lname = request.form.get('lastname'); password = request.form.get('password')
        if not (validate_name('First Name', fname) and validate_name('Last Name', lname) and validate_email(email)):
            return render_template('register_teacher.html')

        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT email COLLATE utf8mb4_general_ci FROM users WHERE email = %s 
            UNION 
            SELECT email COLLATE utf8mb4_general_ci FROM pending_users WHERE email = %s
        """, (email, email))
        
        if cursor.fetchone():
            flash("Email already in use.", "danger"); return render_template('register_teacher.html')

        hashed_pw = generate_password_hash(password); otp = generate_unique_otp(); expiry = datetime.now() + timedelta(minutes=10)
        try:
            cursor.execute("""
                INSERT INTO pending_users (email, password, role, firstname, lastname, middlename, region, province, city, barangay, otp_code, otp_expires_at) 
                VALUES (%s, %s, 'teacher', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (email, hashed_pw, fname, lname, request.form.get('middlename'), request.form.get('region_text'), request.form.get('province_text'), request.form.get('city_text'), request.form.get('barangay_text'), otp, expiry))
            connection.commit(); send_otp_email(email, fname, otp); session['pending_email'] = email; session['firstname'] = fname; session['pending_role'] = 'teacher'
            return redirect(url_for('auth.verify_register'))
        except Exception as e:
            connection.rollback(); flash(f"Error: {e}", "danger")
        finally:
            cursor.close(); connection.close()
    return render_template('register_teacher.html')

#! 4. VERIFY REGISTRATION (OTP)
@auth.route('/verify_register', methods=['GET', 'POST'])
def verify_register():
    email = session.get('pending_email')
    if not email: return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM pending_users WHERE email = %s", (email,))
    p_user = cursor.fetchone()
    if not p_user: cursor.close(); connection.close(); return redirect(url_for('auth.login'))
    remaining_seconds = max(0, int((p_user['otp_expires_at'] - datetime.now()).total_seconds()))
    if request.method == 'POST':
        pin = "".join([request.form.get(f'pin{i}', '') for i in range(1, 7)]).strip()
        if p_user['otp_code'] == pin and datetime.now() < p_user['otp_expires_at']:
            cursor.execute("UPDATE pending_users SET is_otp_verified = 1 WHERE email = %s", (email,))
            connection.commit(); flash("OTP Verified. Please upload documents.", "success")
            cursor.close(); connection.close(); return redirect(url_for('auth.upload_verification'))
        else: flash("Invalid or expired code.", "danger")
    cursor.close(); connection.close()
    return render_template('verify.html', remaining_seconds=remaining_seconds)

#! 5. DOCUMENT UPLOAD (Modified to show Admin Notes)
@auth.route('/upload_verification', methods=['GET', 'POST'])
def upload_verification():
    
    if pending_user_logged_in() == False:
        return redirect(url_for('auth.login'))
     
    email = session.get('pending_email')
    if not email:
        return redirect(url_for('auth.login'))

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)

    cursor.execute("""
        SELECT admin_notes, verification_status 
        FROM pending_users 
        WHERE email = %s
    """, (email,))
    p_data = cursor.fetchone()

    if p_data:
        status = p_data.get('verification_status')

        if status in ['pending_approval', 'approved']:
            cursor.close()
            connection.close()
            return render_template(
                'waiting_approval.html',
                role=session.get('pending_role')
            )

    # ✅ NORMAL FLOW
    if request.method == 'POST':
        file = request.files.get('document')

        if file and allowed_file(file.filename):
            filename = secure_filename(
                f"VERIFY_{int(datetime.now().timestamp())}_{email.split('@')[0]}.pdf"
            )

            file.save(os.path.join(UPLOAD_FOLDER, filename))

            cursor.execute("""
                UPDATE pending_users 
                SET document_path = %s, 
                    verification_status = 'pending_approval', 
                    admin_notes = NULL 
                WHERE email = %s
            """, (filename, email))

            connection.commit()

            cursor.close()
            connection.close()

            session['pending_user_logged_in'] = True

            return render_template(
                'waiting_approval.html',
                role=session.get('pending_role')
            )
        else:
            flash("Please upload a valid PDF file.", "danger")

    cursor.close()
    connection.close()

    return render_template(
        'upload_verification.html',
        admin_notes=p_data['admin_notes'] if p_data else None
    )

#! 6. RESEND OTP (With 5 per hour rate limit)
@auth.route('/resend_otp', methods=['POST'])
def resend_otp():
    email = session.get('pending_email')
    fname = session.get('firstname', 'User')

    if email:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
 
        cursor.execute("SELECT otp_count, last_otp_sent FROM pending_users WHERE email = %s", (email,))
        row = cursor.fetchone()
        
        if not row:
            cursor.close(); connection.close()
            return jsonify({"message": "Registration record not found."}), 404

        now = datetime.now()
        if row['last_otp_sent'] and (now - row['last_otp_sent']) > timedelta(hours=1):
            count = 1
        else:
            count = (row['otp_count'] or 0) + 1

        if count > 5:
            cursor.close(); connection.close()
            return jsonify({"message": "Resend limit reached. Please try again after 1 hour."}), 429
        
        otp = generate_unique_otp()
        expiry = now + timedelta(minutes=10)

        cursor.execute("""
            UPDATE pending_users 
            SET otp_code = %s, otp_expires_at = %s, otp_count = %s, last_otp_sent = NOW() 
            WHERE email = %s
        """, (otp, expiry, count, email))
        
        connection.commit()
        cursor.close(); connection.close()
        
        send_otp_email(email, fname, otp)
        return jsonify({"message": f"New code sent! ({count}/5 attempts this hour)"}), 200

    return jsonify({"message": "Session expired. Please start the registration again."}), 400

#! 7. FORGOT PASSWORD ROUTES (Using otp_table for existing users)
@auth.route('/forgot-password', methods=['POST'])
def forgot_password():
    email = request.form.get('email')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    cursor.execute("SELECT user_id, otp_count, last_otp_sent FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    
    if user:
        now = datetime.now()
        # Reset count if last sent > 1 hour ago
        if user['last_otp_sent'] and (now - user['last_otp_sent']) > timedelta(hours=1):
            count = 1
        else:
            count = (user['otp_count'] or 0) + 1

        if count > 5:
            cursor.close(); connection.close()
            flash("Too many reset attempts. Please wait 1 hour.", "danger")
            return redirect(url_for('auth.login'))

        otp = generate_unique_otp()
        expiry = now + timedelta(minutes=10)
        
        cursor.execute("INSERT INTO otp_table (user_id, otp_code, expires_at, is_used) VALUES (%s, %s, %s, 0)", (user['user_id'], otp, expiry))
        cursor.execute("UPDATE users SET otp_count = %s, last_otp_sent = NOW() WHERE user_id = %s", (count, user['user_id']))
        connection.commit()
        
        send_reset_otp_email(email, otp)
        session.update({'reset_email': email, 'reset_user_id': user['user_id'], 'otp_expiry_timestamp': expiry.timestamp()})
        
        cursor.close(); connection.close()
        return redirect(url_for('auth.verify_reset_otp'))
    
    flash("Email not found.", "warning")
    cursor.close(); connection.close()
    return redirect(url_for('auth.login'))

@auth.route('/resend_reset_otp', methods=['POST'])
def resend_reset_otp():
    email = session.get('reset_email')
    user_id = session.get('reset_user_id')

    if email and user_id:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("SELECT otp_count, last_otp_sent FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        
        now = datetime.now()
        if user['last_otp_sent'] and (now - user['last_otp_sent']) > timedelta(hours=1):
            count = 1
        else:
            count = (user['otp_count'] or 0) + 1

        if count > 5:
            cursor.close(); connection.close()
            return jsonify({"success": False, "message": "Hourly limit reached."}), 429
        
        otp = generate_unique_otp()
        expiry = now + timedelta(minutes=10)
        
        cursor.execute("UPDATE otp_table SET is_used = 1 WHERE user_id = %s", (user_id,))
        cursor.execute("INSERT INTO otp_table (user_id, otp_code, expires_at, is_used) VALUES (%s, %s, %s, 0)", (user_id, otp, expiry))
        cursor.execute("UPDATE users SET otp_count = %s, last_otp_sent = NOW() WHERE user_id = %s", (count, user_id))
        
        connection.commit()
        session['otp_expiry_timestamp'] = expiry.timestamp()
        
        cursor.close(); connection.close()
        send_reset_otp_email(email, otp)
        
        return jsonify({"success": True, "count": count}), 200
    
    return jsonify({"success": False, "message": "Session expired."}), 400
    
@auth.route('/verify-reset-otp', methods=['GET', 'POST'])
def verify_reset_otp():
    if 'reset_email' not in session: 
        return redirect(url_for('auth.login'))
    
    session['in_reset_flow'] = True
    
    if session.get('otp_verified'):
        return redirect(url_for('auth.reset_password'))
    
    rem = int(session.get('otp_expiry_timestamp', 0) - datetime.now().timestamp())

    if request.method == 'POST':
        pin = "".join([request.form.get(f'pin{i}') for i in range(1, 7)])

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT * FROM otp_table 
            WHERE user_id = %s 
              AND otp_code = %s 
              AND is_used = 0 
              AND expires_at > NOW()
        """, (session.get('reset_user_id'), pin))

        if cursor.fetchone():
            cursor.execute("""
                UPDATE otp_table 
                SET is_used = 1 
                WHERE user_id = %s AND otp_code = %s
            """, (session.get('reset_user_id'), pin))

            connection.commit()

            session['otp_verified'] = True

            cursor.close()
            connection.close()

            return redirect(url_for('auth.reset_password'))
        else:
            flash("Invalid code.", "danger")

        cursor.close()
        connection.close()

    return render_template('verify_reset_otp.html', remaining_seconds=rem)


@auth.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if 'reset_email' not in session:
        return redirect(url_for('auth.login'))
    
    session['in_reset_flow'] = True

    if not session.get('otp_verified'):
        return redirect(url_for('auth.verify_reset_otp'))

    if request.method == 'POST':
        pw = request.form.get('password')

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE users 
            SET password = %s 
            WHERE user_id = %s
        """, (generate_password_hash(pw), session.get('reset_user_id')))

        connection.commit()
        session.clear()

        flash("Password updated!", "success")

        cursor.close()
        connection.close()

        return redirect(url_for('auth.login'))

    return render_template('reset_password.html')

#! 8. LOGOUT & AUTO-SUBMIT GRADING
@auth.route('/logout', methods=['POST', 'GET'])
def logout():
    user_id = session.get('user_id'); active_exam_id = session.get('active_exam_id')
    if active_exam_id and user_id:
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True, buffered=True) 
        try:
            cursor.execute("SELECT attempt_id FROM exam_attempts WHERE student_id = %s AND exam_id = %s AND status = 'in-progress' ORDER BY start_time DESC LIMIT 1", (user_id, active_exam_id))
            attempt = cursor.fetchone()
            if attempt:
                cursor.execute("SELECT question_id FROM exam_questions WHERE exam_id = %s", (active_exam_id,))
                questions = cursor.fetchall(); total_score = 0
                for q in questions:
                    cursor.execute("SELECT submitted_answer FROM student_answers WHERE attempt_id = %s AND question_id = %s", (attempt['attempt_id'], q['question_id']))
                    ans = cursor.fetchone()
                    cursor.execute("SELECT option_text FROM options WHERE question_id = %s AND is_correct = 1", (q['question_id'],))
                    corr = cursor.fetchone()
                    if ans and corr and str(ans['submitted_answer']).strip().lower() == str(corr['option_text']).strip().lower():
                        total_score += 1
                        cursor.execute("UPDATE student_answers SET is_correct = 1 WHERE attempt_id = %s AND question_id = %s", (attempt['attempt_id'], q['question_id']))
                cursor.execute("UPDATE exam_attempts SET status = 'finished', end_time = NOW(), score = %s WHERE attempt_id = %s", (total_score, attempt['attempt_id']))
                connection.commit()
        finally:
            if cursor: cursor.close()
            if connection: connection.close()
    session.clear()
    return redirect(url_for('auth.login'))

#! 9. ADMIN APPROVAL (Used by admin.py)
@auth.route('/admin/approve_user/<int:pending_id>', methods=['POST'])
def approve_user(pending_id):
    if not admin_logged_in(): return jsonify({"error": "Unauthorized"}), 403
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM pending_users WHERE pending_id = %s", (pending_id,)); p = cursor.fetchone()
    if p:
        new_id = generate_id('S' if p['role'] == 'student' else 'T')
        try:
            cursor.execute("INSERT INTO users (user_id, email, password, role, is_verified) VALUES (%s, %s, %s, %s, 1)", (new_id, p['email'], p['password'], p['role']))
            if p['role'] == 'student':
                cursor.execute("INSERT INTO students (student_id, email, firstname, lastname, middlename, region, province, city, barangay) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (new_id, p['email'], p['firstname'], p['lastname'], p['middlename'], p['region'], p['province'], p['city'], p['barangay']))
            else:
                cursor.execute("INSERT INTO teachers (teacher_id, email, firstname, lastname, middlename, region, province, city, barangay) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (new_id, p['email'], p['firstname'], p['lastname'], p['middlename'], p['region'], p['province'], p['city'], p['barangay']))
            cursor.execute("DELETE FROM pending_users WHERE pending_id = %s", (pending_id,))
            connection.commit(); return jsonify({"message": "User approved"}), 200
        except Exception as e: connection.rollback(); return jsonify({"error": str(e)}), 500
        finally: cursor.close(); connection.close()
    return jsonify({"error": "Not found"}), 404

#! 7. ADMIN ACTION: REJECT USER (PERMANENT)
@auth.route('/admin/reject_user/<int:pending_id>', methods=['POST'])
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
            # 1. Delete physical file if exists
            if p['document_path']:
                file_path = os.path.join(UPLOAD_FOLDER, p['document_path'])
                if os.path.exists(file_path):
                    os.remove(file_path)

            # 2. Send Rejection Email
            msg = Message(subject='Registration Rejected - TestPoint', sender='verify@testpoint.com', recipients=[p['email']])
            msg.body = f"Hello {p['firstname']},\n\nUnfortunately, your registration has been rejected.\nReason: {reason}\nAdmin Notes: {notes}\n\nYou will need to register again with valid information."
            mail.send(msg)

            # 3. Delete from database
            cursor.execute("DELETE FROM pending_users WHERE pending_id = %s", (pending_id,))
            connection.commit()
            return jsonify({"message": "User rejected and data purged."}), 200
        except Exception as e:
            connection.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            connection.close()
    return jsonify({"error": "User not found"}), 404

#! 9. ADMIN ACTION: REQUEST RESUBMISSION
@auth.route('/admin/resubmit_user/<int:pending_id>', methods=['POST'])
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
                if os.path.exists(file_path):
                    os.remove(file_path)

            full_note = f"Reason: {reason}. {notes}"
            cursor.execute("""
                UPDATE pending_users 
                SET verification_status = 'rejected', 
                    document_path = NULL, 
                    admin_notes = %s 
                WHERE pending_id = %s
            """, (full_note, pending_id))

            msg = Message(subject='Action Required: Resubmit Documents - TestPoint', sender='verify@testpoint.com', recipients=[p['email']])
            msg.body = f"Hello {p['firstname']},\n\nOur admins have reviewed your documents and require a resubmission.\n\ {full_note}\n\nPlease log in to your account to upload the correct documents."
            mail.send(msg)

            connection.commit()
            return jsonify({"message": "Resubmission requested."}), 200
        except Exception as e:
            connection.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            connection.close()
    return jsonify({"error": "User not found"}), 404

