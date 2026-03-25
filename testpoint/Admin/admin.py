from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from testpoint import db_config
from testpoint.Auth.login import admin_logged_in

admin = Blueprint('admin', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/admin/static')

@admin.route('/admin')
def admin_dashboard():
    
    if admin_logged_in():
        return render_template('admin_dashboard.html')
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))