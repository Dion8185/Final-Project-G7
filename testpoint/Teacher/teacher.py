from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from testpoint import db_config
from testpoint.Auth.login import teacher_logged_in

teacher = Blueprint('teacher', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/teacher/static')

@teacher.route('/teacher') 
def teacher_dashboard():
    
    if teacher_logged_in():
        print("Teacher is logged in, rendering dashboard.")
        return render_template('teacher_dashboard.html')
    
    else:
        flash('Please log in as teacher to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))

