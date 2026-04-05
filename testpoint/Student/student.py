from flask import Blueprint, render_template, request, redirect, url_for, flash, session
import mysql
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
    
#! PROFILE

@student.route('/profile', methods=['GET', 'POST'])
def profile():
    if not user_logged_in():
        flash('Please log in as student to access the profile.', 'danger')
        return redirect(url_for('auth.login'))

    user_id = session.get('user_id')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)

    try:
        if request.method == 'POST':
            firstname = request.form.get('firstname')
            middlename = request.form.get('middlename')
            lastname = request.form.get('lastname')
            new_password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')

            cursor.execute("""
                UPDATE students 
                SET firstname = %s, middlename = %s, lastname = %s 
                WHERE student_id = %s
            """, (firstname, middlename, lastname, user_id))

            if new_password:
                if new_password == confirm_password:
                    hashed_pw = generate_password_hash(new_password)
                    cursor.execute(
                        "UPDATE users SET password = %s WHERE user_id = %s",
                        (hashed_pw, user_id)
                    )
                else:
                    connection.rollback()
                    flash('Passwords do not match.', 'warning')
                    return redirect(url_for('student.profile'))

            connection.commit()
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('student.profile'))

        # GET: Fetch Student Data
        cursor.execute("""
            SELECT u.user_id, u.email, u.role, u.created_at,
                   s.firstname, s.middlename, s.lastname,
                   s.region, s.province, s.city, s.barangay
            FROM users u
            JOIN students s ON u.user_id = s.student_id
            WHERE u.user_id = %s
        """, (user_id,))
        user_data = cursor.fetchone()

        return render_template('student_profile.html', user=user_data)

    except mysql.connector.Error as err:
        connection.rollback()
        flash(f'Error: {err}', 'danger')
        return redirect(url_for('student.profile'))

    finally:
        cursor.close()
        connection.close()