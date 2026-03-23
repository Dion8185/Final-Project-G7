from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from testpoint import db_config

auth = Blueprint('auth', __name__, template_folder='templates', static_folder='static', 
                 static_url_path='/auth/static')

register = Blueprint('register', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/register/static')

def user_logged_in():
    return session.get('logged_in', False)

def admin_logged_in():
    return session.get('admin_logged_in', False)

@auth.route('/')
def index():
    if user_logged_in():
        return render_template('babaguhin pa to')
    
    elif admin_logged_in():
        return redirect(url_for('admin.admin_dashboard'))
    
    else:
        return redirect(url_for('auth.login'))

@auth.route('/login', methods=['GET', 'POST'])
def login():
    
    if user_logged_in():
        return render_template('babaguhin pa to')
    
    if admin_logged_in():
        return redirect(url_for('admin.admin_dashboard'))
     
    if request.method == 'POST':
        username_input = request.form['username']
        password_input = request.form['password']
        
        if username_input == 'admin' and password_input == 'admin123':
            session['admin_logged_in'] = True
            flash('Admin login successful!', 'success')
            return redirect(url_for('admin.admin_dashboard'))
        

    
    return render_template('login.html')