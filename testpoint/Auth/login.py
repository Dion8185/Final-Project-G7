from flask import Blueprint, render_template, request, redirect, url_for, flash, session
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

@auth.route('/')
def index():
    if user_logged_in():
        return redirect(url_for('student.student_dashboard'))
    
    elif admin_logged_in():
        return redirect(url_for('admin.admin_dashboard'))
    
    else:
        return redirect(url_for('auth.login'))

@auth.route('/login', methods=['GET', 'POST'])
def login():
    
    if user_logged_in():
        return redirect(url_for('student.student_dashboard'))
    
    if admin_logged_in():
        return redirect(url_for('admin.admin_dashboard'))
     
    if request.method == 'POST':
        email_input = request.form['email']
        password_input = request.form['password']
        
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        query_fetch_user = "SELECT * FROM users WHERE email = %s"
        cursor.execute(query_fetch_user, (email_input,))
        user = cursor.fetchone()
        cursor.close()
        
        if not user:
            flash('Invalid username or password!', 'error')
            return render_template('login.html')

        user_userID = user[0]
        user_email = user[1]
        user_password = user[2]
        user_role = user[3]
        user_isVerified = user[4]
        
        if user_isVerified == 1:
                if user_role == 'admin' and user_email == email_input and password_input == user_password:
                    session['admin_logged_in'] = True
                    flash('Admin login successful!', 'success')
                    return redirect(url_for('admin.admin_dashboard'))
                
                elif user_role == 'examinee' and user_email == email_input and password_input == user_password:
                    session['user_logged_in'] = True
                    flash('User login successful!', 'success')
                    return redirect(url_for('student.student_dashboard'))
                
                else:
                    flash('Invalid username or password!', 'error')

        # if email_input == 'admin@example.com' and password_input == 'admin123':
        #     session['admin_logged_in'] = True
        #     flash('Admin login successful!', 'success')
        #     return redirect(url_for('admin.admin_dashboard'))
        
        # elif email_input == 'user@example.com' and password_input == 'user123':
        #     session['user_logged_in'] = True
        #     flash('User login successful!', 'success')
        #     return redirect(url_for('student.student_dashboard'))
        
        else:
            flash('Invalid username or password!', 'error')
    
    return render_template('login.html')

@auth.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))