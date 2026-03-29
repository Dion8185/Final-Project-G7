from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from testpoint import db_config
from testpoint.Auth.login import admin_logged_in

admin = Blueprint('admin', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/admin/static')

@admin.route('/')
def admin_dashboard():
    
    if admin_logged_in():
        return render_template('admin_dashboard.html')
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))

@admin.route('/manage_accounts' )
def manage_accounts():
    
    if admin_logged_in():
        return render_template('admin_accounts.html')
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))

@admin.route('/manage_courses')
def manage_courses():
    
    if admin_logged_in():
        return render_template('admin_courses.html')
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
    
@admin.route('/oversee_exams')
def oversee_exams():
    if admin_logged_in():
        return render_template('admin_exams.html')
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
    
@admin.route('/user_logs')
def user_logs():
    if admin_logged_in():
        return render_template('admin_logs.html')
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
    
@admin.route('/settings')
def settings():
    if admin_logged_in():
        return render_template('admin_settings.html')
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
    