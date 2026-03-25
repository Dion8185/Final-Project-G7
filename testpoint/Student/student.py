from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from testpoint import db_config
from testpoint.Auth.login import user_logged_in

student = Blueprint('student', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/student/static')

@student.route('/student')
def student_dashboard():
    
    if user_logged_in():
        return render_template('student_dashboard.html')
    
    else:
        flash('Please log in to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))