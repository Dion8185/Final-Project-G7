from flask import Blueprint, render_template, request, redirect, url_for, flash, session
import mysql.connector
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
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute(""" SELECT 
                            u.user_id,
                            -- Choose name from students or teachers
                            COALESCE(s.firstname, t.firstname) AS firstname,
                            COALESCE(s.middlename, t.middlename) AS middlename,
                            COALESCE(s.lastname, t.lastname) AS lastname,
                            u.email,
                            u.role,
                            u.is_verified,
                            u.created_at
                            FROM users u
                            LEFT JOIN students s
                                ON u.user_id = s.student_id
                            LEFT JOIN teachers t
                                ON u.user_id = t.teacher_id
                            WHERE u.is_active = 1;
        """)
        users = cursor.fetchall()
        cursor.close()
        connection.close()
        


        return render_template('admin_accounts.html', users=users)
    
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
    
@admin.route('/trashed_accounts')
def trashed_accounts():
    if admin_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute(""" SELECT 
                            u.user_id,
                            -- Choose name from students or teachers
                            COALESCE(s.firstname, t.firstname) AS firstname,
                            COALESCE(s.middlename, t.middlename) AS middlename,
                            COALESCE(s.lastname, t.lastname) AS lastname,
                            u.email,
                            u.role,
                            u.is_verified,
                            u.created_at
                            FROM users u
                            LEFT JOIN students s
                                ON u.user_id = s.student_id
                            LEFT JOIN teachers t
                                ON u.user_id = t.teacher_id
                            WHERE u.is_active = NULL OR u.is_active = 0;
        """)
        trashed_users = cursor.fetchall()
        cursor.close()
        connection.close()
        
        return render_template('admin_trashed.html', trashed_users=trashed_users)
    
    else:
        flash('Please log in as admin to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))