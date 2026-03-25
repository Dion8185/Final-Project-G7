from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash, generate_password_hash
from testpoint import db_config
import mysql.connector

auth = Blueprint('auth', __name__, template_folder='templates', static_folder='static', 
                 static_url_path='/auth/static')

register = Blueprint('register', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/register/static')

def user_logged_in():
    return session.get('user_logged_in', False)

def admin_logged_in():
    return session.get('admin_logged_in', False)

def teacher_logged_in():
    return session.get('teacher_logged_in', False)

@auth.route('/')
def index():
    if user_logged_in():
        return redirect(url_for('student.student_dashboard'))
    
    elif admin_logged_in():
        return redirect(url_for('admin.admin_dashboard'))
    
    elif teacher_logged_in():
        return redirect(url_for('teacher.teacher_dashboard'))
    
    else:
        return redirect(url_for('auth.login'))

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
        cursor = connection.cursor()

        query_fetch_user = "SELECT * FROM users WHERE email = %s"
        cursor.execute(query_fetch_user, (email_input,))
        user = cursor.fetchone()

        cursor.close()
        connection.close()

        if not user:
            flash('Input an email and password!', 'danger')
            return render_template('login.html')
        
        user_password = user[2]
        user_role = user[3]
        user_isVerified = user[4]
        
        if user_isVerified != 1:
            flash('Your account is not verified yet. Please wait for admin approval.', 'warning')
            return render_template('login.html')

        if not (user_password == password_input):
            flash('Invalid username or password!', 'danger')
            return render_template('login.html')

        if user_role == 'admin':
            session['admin_logged_in'] = True
            return redirect(url_for('admin.admin_dashboard'))

        elif user_role == 'student':
            session['user_logged_in'] = True
            return redirect(url_for('student.student_dashboard'))

        elif user_role == 'teacher':
            session['teacher_logged_in'] = True
            return redirect(url_for('teacher.teacher_dashboard'))

    return render_template('login.html')

@auth.route('/register', methods=['GET', 'POST'])
def register_page():
    
    if user_logged_in():
        return redirect(url_for('student.student_dashboard'))
   
    if admin_logged_in():
        return redirect(url_for('admin.admin_dashboard'))
    
    if request.method == 'POST':
        firstname = request.form.get('firstname','').strip()
        middlename = request.form.get('middlename','').strip()
        lastname = request.form.get('lastname','').strip()
        email = request.form.get('email','').strip()
        password = request.form.get('password','').strip()
        confirm_password = request.form.get('confirm_password','').strip()
        role = request.form.get('role','').strip()
        
        if not all([firstname, lastname, email, password, confirm_password, role]):
            flash('Please fill in all required fields.', 'danger')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'danger')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')
        
        if role not in ['admin', 'examinee']:
            flash('Invalid role selected.', 'danger')
            return render_template('register.html')
    
    return redirect(url_for('register.register'))

@auth.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))