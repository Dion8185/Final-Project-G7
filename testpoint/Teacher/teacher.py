from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from testpoint import db_config
from testpoint.Auth.login import teacher_logged_in
import mysql.connector
import pandas as pd
import os

teacher = Blueprint('teacher', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/teacher/static')

@teacher.route('/')
def teacher_dashboard():
    if teacher_logged_in():
        return render_template('teacher_dashboard.html')
    else:
        flash('Please log in to access the teacher dashboard.', 'danger')
        return redirect(url_for('auth.login'))

#! ── ENROLLMENT MANAGEMENT ──

@teacher.route('/my_students')
def my_students():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        # Get courses assigned to THIS teacher
        cursor.execute("SELECT * FROM courses WHERE teacher_id = %s", (teacher_id,))
        my_courses = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('teacher_my_courses.html', courses=my_courses)
    return redirect(url_for('auth.login'))

@teacher.route('/manage_enrollees/<int:course_id>')
def manage_enrollees(course_id):
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        # Security check: Does teacher own this course?
        cursor.execute("SELECT * FROM courses WHERE course_id = %s AND teacher_id = %s", (course_id, teacher_id))
        course = cursor.fetchone()
        
        if not course:
            flash("Access denied.", "danger")
            return redirect(url_for('teacher.my_students'))

        cursor.execute("""
            SELECT s.student_id, s.firstname, s.lastname, s.email, e.enrollment_id, e.enrolled_at 
            FROM students s
            JOIN enrollments e ON s.student_id = e.student_id
            WHERE e.course_id = %s
        """, (course_id,))
        enrollees = cursor.fetchall()
        
        cursor.execute("SELECT student_id, firstname, lastname FROM students")
        all_students = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('teacher_enrollees.html', course=course, enrollees=enrollees, all_students=all_students)
    return redirect(url_for('auth.login'))

@teacher.route('/enroll_student', methods=['POST'])
def enroll_student():
    if teacher_logged_in():
        student_id = request.form.get('student_id')
        course_id = request.form.get('course_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("INSERT INTO enrollments (student_id, course_id) VALUES (%s, %s)", (student_id, course_id))
            connection.commit()
            flash('Student enrolled successfully!', 'success')
        except mysql.connector.Error:
            flash('Student is already in this class.', 'warning')
        finally:
            cursor.close()
            connection.close()
        return redirect(url_for('teacher.manage_enrollees', course_id=course_id))
    return redirect(url_for('auth.login'))

@teacher.route('/unenroll_student/<int:enrollment_id>/<int:course_id>', methods=['POST'])
def unenroll_student(enrollment_id, course_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("DELETE FROM enrollments WHERE enrollment_id = %s", (enrollment_id,))
        connection.commit()
        cursor.close()
        connection.close()
        flash('Student removed.', 'success')
        return redirect(url_for('teacher.manage_enrollees', course_id=course_id))
    return redirect(url_for('auth.login'))


#! ── EXAM MANAGEMENT ──

@teacher.route('/manage_exams')
def manage_exams():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT e.*, c.course_name 
            FROM exams e 
            JOIN courses c ON e.course_id = c.course_id 
            WHERE c.teacher_id = %s
        """, (teacher_id,))
        exams = cursor.fetchall()
        
        cursor.execute("SELECT course_id, course_name FROM courses WHERE teacher_id = %s", (teacher_id,))
        my_courses = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('teacher_exams.html', exams=exams, courses=my_courses)
    return redirect(url_for('auth.login'))

@teacher.route('/add_exam', methods=['POST'])
def add_exam():
    if teacher_logged_in():
        course_id = request.form.get('course_id')
        title = request.form.get('title')
        duration = request.form.get('duration')
        pass_percent = request.form.get('pass_percentage')
        teacher_id = session.get('user_id')

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("""
                INSERT INTO exams (course_id, title, duration_minutes, pass_percentage, created_by) 
                VALUES (%s, %s, %s, %s, %s)
            """, (course_id, title, duration, pass_percent, teacher_id))
            connection.commit()
            flash('Exam created successfully!', 'success')
        except mysql.connector.Error as err:
            flash(f'Error: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()
        return redirect(url_for('teacher.manage_exams'))
    return redirect(url_for('auth.login'))


#! ── QUESTION BANK & EXCEL IMPORT ──

@teacher.route('/manage_questions/<int:exam_id>')
def manage_questions(exam_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM exams WHERE exam_id = %s", (exam_id,))
        exam = cursor.fetchone()
        
        cursor.execute("SELECT * FROM questions WHERE exam_id = %s", (exam_id,))
        questions = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('teacher_questions.html', exam=exam, questions=questions)
    return redirect(url_for('auth.login'))

@teacher.route('/import_questions/<int:exam_id>', methods=['POST'])
def import_questions(exam_id):
    if teacher_logged_in():
        file = request.files.get('excel_file')
        if not file or not file.filename.endswith(('.xlsx', '.xls')):
            flash('Please upload a valid Excel file.', 'danger')
            return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

        try:
            df = pd.read_excel(file)
            connection = mysql.connector.connect(**db_config)
            cursor = connection.cursor()

            for _, row in df.iterrows():
                # Basic Import Logic (Adjust columns based on your Excel template)
                cursor.execute("""
                    INSERT INTO questions (exam_id, question_text, question_type, difficulty, points)
                    VALUES (%s, %s, %s, %s, %s)
                """, (exam_id, row['Question'], row['Type'], row['Difficulty'], row['Points']))
                
                # If Multiple Choice, you would then insert into the 'options' table here
                
            connection.commit()
            flash('Questions imported successfully!', 'success')
        except Exception as e:
            flash(f'Import failed: {str(e)}', 'danger')
        finally:
            cursor.close()
            connection.close()
        
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))
    return redirect(url_for('auth.login'))


#! ── MONITORING & ANALYSIS ──

@teacher.route('/monitor')
def student_monitor():
    if teacher_logged_in():
        return render_template('teacher_monitor.html')
    else:
        flash('Please log in to access the monitoring dashboard.', 'danger')
        return redirect(url_for('auth.login'))

@teacher.route('/analysis')
def exam_analysis():
    if teacher_logged_in():
        return render_template('teacher_analysis.html')
    else:
        flash('Please log in to access the analysis dashboard.', 'danger')
        return redirect(url_for('auth.login')) 