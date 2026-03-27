import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash, generate_password_hash
from testpoint import db_config
import mysql.connector
from datetime import datetime

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

            if not value:
                flash(f'{field_name} is required.', 'danger')
                return False
            
            if re.search(r'(.)\1{3,}', value):
                flash(f'{field_name} contains too many repeated characters.', 'danger')
                return False

            if not NAME_REGEX.match(value):
                flash(f'{field_name} contains invalid characters or format.', 'danger')
                return False

            return True
        
def validate_email(email):
    email = email.strip()

    if not email:
        flash('Email is required.', 'danger')
        return False

    if ' ' in email:
        flash('Email address cannot contain spaces.', 'danger')
        return False
    
    if len(email) > 254:
        flash('Email address is too long. Maximum length is 254 characters.', 'danger')
        return False

    if not EMAIL_REGEX.match(email):
        flash('Please enter a valid email address.', 'danger')
        return False

    return True

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

        query_fetch_user = "SELECT * FROM users WHERE email = %s;"
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
        
        
        if user_role == 'admin' and user_password == password_input:
            session['admin_logged_in'] = True
            return redirect(url_for('admin.admin_dashboard'))
        
        if not check_password_hash(user_password, password_input):
            flash('Invalid username or password!', 'danger')
            return render_template('login.html')

        elif user_role == 'student':
            session['user_logged_in'] = True
            return redirect(url_for('student.student_dashboard'))

        elif user_role == 'teacher':
            session['teacher_logged_in'] = True
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
        firstname = request.form.get('firstname','').strip()
        middlename = request.form.get('middlename','').strip()
        lastname = request.form.get('lastname','').strip()
        email = request.form.get('email','').strip()
        password = request.form.get('password','').strip()
        confirm_password = request.form.get('confirm_password','').strip()
        region = request.form.get('region_text','').strip()
        province = request.form.get('province_text','').strip()
        city = request.form.get('city_text','').strip()
        barangay = request.form.get('barangay_text','').strip()

        if not all([firstname, lastname, email, password, confirm_password, region, province, city, barangay]):
            flash('Please fill in all required fields.', 'danger')
            return render_template('register.html')

        if not validate_name("First name", firstname):
            return render_template('register.html')

        if middlename and not validate_name("Middle name", middlename):
            return render_template('register.html')

        if not validate_name("Last name", lastname):
            return render_template('register.html')

        if not validate_email(email):
            return render_template('register.html')

        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'danger')
            return render_template('register.html')

        if not any(char.isupper() for char in password):
            flash('Password must contain at least one uppercase letter.', 'danger')
            return render_template('register.html')

        if not any(char.islower() for char in password):
            flash('Password must contain at least one lowercase letter.', 'danger')
            return render_template('register.html')

        if not any(char.isdigit() for char in password):
            flash('Password must contain at least one digit.', 'danger')
            return render_template('register.html')

        if not any(not char.isalnum() for char in password):
            flash('Password must contain at least one special character.', 'danger')
            return render_template('register.html')

        if ' ' in password:
            flash('Password cannot contain spaces.', 'danger')
            return render_template('register.html')

        if password.lower() in ['password', '123456', '12345678', 'qwerty', 'abc123']:
            flash('Password is too common. Please choose a stronger password.', 'danger')
            return render_template('register.html')

        if password == email:
            flash('Password cannot be the same as the email address.', 'danger')
            return render_template('register.html')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')

        hashed_password = generate_password_hash(password)

        try:
            connection = mysql.connector.connect(**db_config)
            connection.start_transaction()  
            cursor = connection.cursor()

            query_check_email = "SELECT user_id FROM users WHERE email = %s;"
            cursor.execute(query_check_email, (email,))
            if cursor.fetchone():
                flash('Email is already registered.', 'danger')
                connection.rollback()
                return render_template('register.html')

            student_id = generate_id('S')
            
            query_insert_user = """
                INSERT INTO users (user_id, email, password, role)
                VALUES (%s, %s, %s, 'student');
            """
            cursor.execute(query_insert_user, (student_id, email, hashed_password))

            query_insert_student = """
                INSERT INTO students (student_id, email, firstname, middlename, lastname, region, province, city, barangay)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
            """
            cursor.execute(query_insert_student, (student_id, email, firstname, middlename, lastname, region, province, city, barangay))

            connection.commit()
            flash('Registration successful!', 'success')
            return redirect(url_for('auth.login'))

        except mysql.connector.Error as err:
            connection.rollback()
            flash(f'Error: {err}', 'danger')
            return render_template('register.html')

        finally:
            cursor.close()
            connection.close()

    return render_template('register.html')

@auth.route('/register/teacher', methods=['GET', 'POST'])
def register_teacher():
    return "Teacher registration page - Under construction"

    
@auth.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


def generate_id(role):
    """
    role: 'T' (Teacher) or 'S' (Student)
    """

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    year_suffix = datetime.now().strftime("%y") 
    like_pattern = f"{role}{year_suffix}-%"

    query = """
        SELECT user_id
        FROM users
        WHERE user_id LIKE %s
        ORDER BY user_id DESC
        LIMIT 1;
    """

    cursor.execute(query, (like_pattern,))
    result = cursor.fetchone()

    if result:
        last_id = result[0] 

        try:
            last_number = int(last_id.split('-')[1])
        except (IndexError, ValueError):
            last_number = 0 

        new_number = last_number + 1
    else:
        new_number = 1 

    cursor.close()
    connection.close()
    new_id = f"{role}{year_suffix}-{str(new_number).zfill(4)}"

    return new_id