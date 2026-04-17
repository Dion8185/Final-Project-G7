from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from testpoint import db_config
from testpoint.Auth.login import teacher_logged_in
import mysql.connector
import pandas as pd 
import io
from datetime import datetime

teacher = Blueprint('teacher', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/teacher/static')

#! 1. DASHBOARD
@teacher.route('/')
def teacher_dashboard():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        firstname = session.get('firstname')
        lastname = session.get('lastname')
        
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        try:
            cursor.execute("SELECT COUNT(*) as count FROM courses WHERE teacher_id = %s", (teacher_id,))
            course_count = cursor.fetchone()['count']
            
            cursor.execute("""
                SELECT COUNT(*) as count FROM exams e 
                JOIN courses c ON e.course_id = c.course_id 
                WHERE c.teacher_id = %s
            """, (teacher_id,))
            exam_count = cursor.fetchone()['count']
            
            cursor.execute("""
                SELECT COUNT(DISTINCT e.student_id) as count FROM enrollments e
                JOIN courses c ON e.course_id = c.course_id
                WHERE c.teacher_id = %s
            """, (teacher_id,))
            student_count = cursor.fetchone()['count']

            cursor.execute("""
                SELECT COUNT(*) as count FROM exam_attempts ea
                JOIN exams ex ON ea.exam_id = ex.exam_id
                JOIN courses c ON ex.course_id = c.course_id
                WHERE c.teacher_id = %s AND ea.status = 'in-progress'
            """, (teacher_id,))
            active_examinees = cursor.fetchone()['count']

        except mysql.connector.Error as err:
            flash(f"Error loading stats: {err}", "danger")
            course_count = exam_count = student_count = active_examinees = 0
        finally:
            cursor.close()
            connection.close()
        
        return render_template('teacher_dashboard.html', 
                               firstname=firstname, 
                               lastname=lastname,
                               course_count=course_count,
                               exam_count=exam_count,
                               student_count=student_count,
                               active_examinees=active_examinees)
    else:
        flash('Please log in to access the teacher dashboard.', 'danger')
        return redirect(url_for('auth.login'))

#! 2. QUESTION BANK (Grouping by Course)
@teacher.route('/question_bank')
def question_bank():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        # Get courses assigned to teacher with a count of questions in each course's bank
        cursor.execute("""
            SELECT c.*, 
            (SELECT COUNT(*) FROM questions WHERE course_id = c.course_id) as question_count
            FROM courses c 
            WHERE c.teacher_id = %s
        """, (teacher_id,))
        courses = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('teacher_bank_courses.html', courses=courses)
    return redirect(url_for('auth.login'))

@teacher.route('/question_bank/<int:course_id>')
def course_question_bank(course_id):
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        # Security: Ensure teacher owns this course
        cursor.execute("SELECT * FROM courses WHERE course_id = %s AND teacher_id = %s", (course_id, teacher_id))
        course = cursor.fetchone()
        if not course:
            flash("Unauthorized access.", "danger")
            return redirect(url_for('teacher.question_bank'))

        # Get all questions belonging to this course bank
        cursor.execute("SELECT * FROM questions WHERE course_id = %s", (course_id,))
        questions = cursor.fetchall()
        
        for q in questions:
            cursor.execute("SELECT * FROM options WHERE question_id = %s", (q['question_id'],))
            q['options'] = cursor.fetchall()

        cursor.close()
        connection.close()
        return render_template('teacher_bank_details.html', course=course, questions=questions)
    return redirect(url_for('auth.login'))

#! 3. BANK CRUD ACTIONS
@teacher.route('/add_bank_question/<int:course_id>', methods=['POST'])
def add_bank_question(course_id):
    if teacher_logged_in():
        q_text = request.form.get('question_text')
        q_type = request.form.get('question_type')
        difficulty = request.form.get('difficulty')

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("""
                INSERT INTO questions (course_id, question_text, question_type, difficulty)
                VALUES (%s, %s, %s, %s)
            """, (course_id, q_text, q_type, difficulty))
            q_id = cursor.lastrowid

            if q_type == 'multiple_choice':
                options = request.form.getlist('options[]')
                correct_idx = int(request.form.get('correct_option'))
                for i, opt_text in enumerate(options):
                    cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", 
                                   (q_id, opt_text, 1 if i == correct_idx else 0))
            elif q_type == 'true_false':
                correct_val = request.form.get('tf_correct')
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'True', 1 if correct_val == 'True' else 0))
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'False', 1 if correct_val == 'False' else 0))
            elif q_type == 'identification':
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, request.form.get('ident_answer'), 1))

            connection.commit()
            flash('Question added to Bank!', 'success')
        finally:
            cursor.close()
            connection.close()
        return redirect(url_for('teacher.course_question_bank', course_id=course_id))
    return redirect(url_for('auth.login'))

@teacher.route('/delete_bank_question/<int:q_id>/<int:course_id>', methods=['POST'])
def delete_bank_question(q_id, course_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        # This will delete options too if ON DELETE CASCADE is set
        cursor.execute("DELETE FROM questions WHERE question_id = %s", (q_id,))
        connection.commit()
        cursor.close()
        connection.close()
        flash('Question permanently deleted from Bank.', 'success')
        return redirect(url_for('teacher.course_question_bank', course_id=course_id))
    
@teacher.route('/bulk_delete_bank_questions/<int:course_id>', methods=['POST'])
def bulk_delete_bank_questions(course_id):
    if teacher_logged_in():
        # Get the list of question IDs from the checkboxes
        question_ids = request.form.getlist('question_ids[]')
        
        if not question_ids:
            flash("No questions selected.", "warning")
            return redirect(url_for('teacher.course_question_bank', course_id=course_id))

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            # SQL IN clause to delete all selected IDs
            format_strings = ','.join(['%s'] * len(question_ids))
            cursor.execute(f"DELETE FROM questions WHERE question_id IN ({format_strings})", tuple(question_ids))
            connection.commit()
            flash(f'Successfully deleted {len(question_ids)} questions.', 'success')
        except mysql.connector.Error as err:
            flash(f'Error: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()
            
        return redirect(url_for('teacher.course_question_bank', course_id=course_id))
    return redirect(url_for('auth.login'))

#! (EXISTING ROUTES: MY COURSES, ENROLLEES, EXAMS, MONITORING, ETC - KEPT UNTOUCHED)
@teacher.route('/my_courses')
def my_courses():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT c.*, (SELECT COUNT(*) FROM enrollments WHERE course_id = c.course_id) as student_count FROM courses c WHERE teacher_id = %s", (teacher_id,))
        courses = cursor.fetchall()
        cursor.close()
        connection.close()
        return render_template('teacher_my_courses.html', courses=courses)
    return redirect(url_for('auth.login'))

@teacher.route('/manage_enrollees/<int:course_id>')
def manage_enrollees(course_id):
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM courses WHERE course_id = %s AND teacher_id = %s", (course_id, teacher_id))
        course = cursor.fetchone()
        if not course: return redirect(url_for('teacher.my_courses'))
        cursor.execute("SELECT e.enrollment_id, s.student_id, s.firstname, s.lastname, u.email, e.enrolled_at FROM enrollments e JOIN students s ON e.student_id = s.student_id JOIN users u ON s.student_id = u.user_id WHERE e.course_id = %s", (course_id,))
        enrollees = cursor.fetchall()
        cursor.execute("SELECT s.student_id, s.firstname, s.lastname FROM students s INNER JOIN users u ON s.student_id = u.user_id LEFT JOIN enrollments e ON s.student_id = e.student_id AND e.course_id = %s WHERE u.is_verified = 1 AND e.student_id IS NULL", (course_id,))
        all_students = cursor.fetchall()
        cursor.close()
        connection.close()
        return render_template('teacher_enrollees.html', course=course, enrollees=enrollees, all_students=all_students)
    return redirect(url_for('auth.login'))

@teacher.route('/manage_exams')
def manage_exams():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT e.*, c.course_name, c.course_code, e.date_time FROM exams e JOIN courses c ON e.course_id = c.course_id WHERE c.teacher_id = %s AND e.archived = 0;", (teacher_id,))
        exams = cursor.fetchall()
        cursor.execute("SELECT course_id, course_name FROM courses WHERE teacher_id = %s", (teacher_id,))
        courses = cursor.fetchall()
        cursor.close()
        connection.close()
        return render_template('teacher_exams.html', exams=exams, courses=courses, now=datetime.now())
    return redirect(url_for('auth.login'))

@teacher.route('/add_exam', methods=['POST'])
def add_exam():
    if teacher_logged_in():
        course_id = request.form.get('course_id')
        title = request.form.get('title')
        duration = request.form.get('duration')
        pass_percent = request.form.get('pass_percentage')
        schedule = request.form.get('schedule')
        teacher_id = session.get('user_id')

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("""
                INSERT INTO exams (course_id, title, duration_minutes, pass_percentage, date_time, created_by, is_active) 
                VALUES (%s, %s, %s, %s, %s, %s, 0)
            """, (course_id, title, duration, pass_percent, schedule, teacher_id))
            new_exam_id = cursor.lastrowid # Get the ID of the exam just created
            connection.commit()
            
            flash('Exam Header Created! Now add your questions via Manual Entry or Excel Import.', 'success')
            # REDIRECT DIRECTLY TO QUESTION MANAGEMENT
            return redirect(url_for('teacher.manage_questions', exam_id=new_exam_id))
            
        except mysql.connector.Error as err:
            flash(f'Database Error: {err}', 'danger')
            return redirect(url_for('teacher.manage_exams'))
        finally:
            cursor.close()
            connection.close()
    return redirect(url_for('auth.login'))


@teacher.route('/update_exam', methods=['POST'])
def update_exam():
    if teacher_logged_in():
        exam_id = request.form.get('exam_id'); title = request.form.get('title'); duration = request.form.get('duration'); pass_percent = request.form.get('pass_percentage'); status = request.form.get('status'); schedule = request.form.get('schedule')
        status_int = 1 if status and status.lower() == 'active' else 0
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        try:
            cursor.execute("UPDATE exams SET title = %s, duration_minutes = %s, pass_percentage = %s, is_active = %s, date_time = %s WHERE exam_id = %s", (title, duration, pass_percent, status_int, schedule, exam_id))
            connection.commit(); flash('Exam configuration updated!', 'success')
        finally: cursor.close(); connection.close()
        return redirect(url_for('teacher.manage_exams'))
    return redirect(url_for('auth.login'))

@teacher.route('/manage_questions/<int:exam_id>')
def manage_questions(exam_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM exams WHERE exam_id = %s", (exam_id,))
        exam = cursor.fetchone()
        cursor.execute("SELECT q.* FROM questions q JOIN exam_questions eq ON q.question_id = eq.question_id WHERE eq.exam_id = %s", (exam_id,))
        questions = cursor.fetchall()
        for q in questions:
            cursor.execute("SELECT * FROM options WHERE question_id = %s", (q['question_id'],))
            q['options'] = cursor.fetchall()
        cursor.execute("SELECT * FROM questions WHERE course_id = %s AND question_id NOT IN (SELECT question_id FROM exam_questions WHERE exam_id = %s)", (exam['course_id'], exam_id))
        bank_questions = cursor.fetchall()
        cursor.close(); connection.close()
        return render_template('teacher_questions.html', exam=exam, questions=questions, bank_questions=bank_questions)
    return redirect(url_for('auth.login'))

@teacher.route('/add_question/<int:exam_id>', methods=['POST'])
def add_question(exam_id):
    if teacher_logged_in():
        q_text = request.form.get('question_text'); q_type = request.form.get('question_type'); difficulty = request.form.get('difficulty')
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT course_id FROM exams WHERE exam_id = %s", (exam_id,))
            course_id = cursor.fetchone()['course_id']
            cursor.execute("INSERT INTO questions (course_id, question_text, question_type, difficulty) VALUES (%s, %s, %s, %s)", (course_id, q_text, q_type, difficulty))
            q_id = cursor.lastrowid
            cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id))
            if q_type == 'multiple_choice':
                options = request.form.getlist('options[]'); correct_idx = int(request.form.get('correct_option'))
                for i, opt_text in enumerate(options): cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, opt_text, 1 if i == correct_idx else 0))
            elif q_type == 'true_false':
                correct_val = request.form.get('tf_correct')
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'True', 1 if correct_val == 'True' else 0))
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'False', 1 if correct_val == 'False' else 0))
            elif q_type == 'identification': cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, request.form.get('ident_answer'), 1))
            connection.commit(); flash('Added to bank and linked!', 'success')
        finally: cursor.close(); connection.close()
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))
    return redirect(url_for('auth.login'))

@teacher.route('/import_questions', methods=['POST'])
def import_questions():
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    exam_id = request.form.get('exam_id'); file = request.files.get('excel_file'); connection = None; cursor = None
    if not file or not file.filename.endswith(('.xlsx', '.xls')): return redirect(url_for('teacher.manage_questions', exam_id=exam_id))
    try:
        df = pd.read_excel(file, engine='openpyxl'); connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT course_id FROM exams WHERE exam_id = %s", (exam_id,))
        course_id = cursor.fetchone()['course_id']
        for _, row in df.iterrows():
            cursor.execute("INSERT INTO questions (course_id, question_text, question_type, difficulty) VALUES (%s, %s, %s, %s)", (course_id, row['Question'], row['Type'], row['Difficulty']))
            q_id = cursor.lastrowid
            cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id))
            q_type = str(row['Type']).lower().strip(); correct_answer = str(row['Answer']).strip()
            if q_type == 'multiple_choice':
                opts = [str(row['OptA']), str(row['OptB']), str(row['OptC']), str(row['OptD'])]
                for opt in opts: cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, opt, 1 if opt.strip() == correct_answer else 0))
            elif q_type == 'true_false':
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'True', 1 if correct_answer.lower() == 'true' else 0))
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'False', 1 if correct_answer.lower() == 'false' else 0))
            elif q_type == 'identification': cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, correct_answer, 1))
        connection.commit(); flash('Imported!', 'success')
    except Exception as e: flash(f'Error: {e}', 'danger')
    finally:
        if cursor: cursor.close()
        if connection: connection.close()
    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

@teacher.route('/link_from_bank/<int:exam_id>/<int:q_id>', methods=['POST'])
def link_from_bank(exam_id, q_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        try: cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id)); connection.commit(); flash('Linked!', 'success')
        except: flash('Already in exam.', 'warning')
        finally: cursor.close(); connection.close()
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

@teacher.route('/delete_question/<int:q_id>/<int:exam_id>', methods=['POST'])
def delete_question(q_id, exam_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("DELETE FROM exam_questions WHERE question_id = %s AND exam_id = %s", (q_id, exam_id))
        connection.commit(); cursor.close(); connection.close(); flash('Unlinked from exam.', 'success')
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

@teacher.route('/student_monitor')
def student_monitor():
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    teacher_id = session.get('user_id'); connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT ea.*, s.firstname, s.lastname, ex.title, ex.duration_minutes FROM exam_attempts ea JOIN students s ON ea.student_id = s.student_id JOIN exams ex ON ea.exam_id = ex.exam_id JOIN courses c ON ex.course_id = c.course_id WHERE c.teacher_id = %s AND ea.status = 'in-progress' ORDER BY ea.start_time DESC", (teacher_id,))
    attempts = cursor.fetchall(); cursor.close(); connection.close()
    return render_template('teacher_monitor.html', attempts=attempts)

@teacher.route('/view_results/<int:exam_id>')
def view_results(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)

    cursor.execute("SELECT * FROM exams WHERE exam_id = %s", (exam_id,))
    exam = cursor.fetchone()
    
    cursor.execute("""
        SELECT ea.attempt_id, s.student_id, s.firstname, s.lastname, 
               ea.score, ea.status, ea.end_time, ea.tab_switches,
        (SELECT COUNT(*) FROM exam_questions WHERE exam_id = %s) as total_questions
        FROM exam_attempts ea
        JOIN students s ON ea.student_id = s.student_id
        WHERE ea.exam_id = %s
        ORDER BY s.lastname ASC
    """, (exam_id, exam_id))
    results = cursor.fetchall()
    
    cursor.close()
    connection.close()
    return render_template('teacher_exam_results.html', exam=exam, results=results)

@teacher.route('/reset_exam/<int:attempt_id>/<int:exam_id>', methods=['POST'])
def reset_exam(attempt_id, exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM exam_attempts WHERE attempt_id = %s", (attempt_id,))
        connection.commit()
        flash('Student exam progress has been reset successfully.', 'success')
    except mysql.connector.Error as err:
        flash(f'Error: {err}', 'danger')
    finally:
        cursor.close()
        connection.close()
    
    return redirect(url_for('teacher.view_results', exam_id=exam_id))

@teacher.route('/exam_analysis')
def exam_analysis():
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    teacher_id = session.get('user_id'); connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT e.exam_id, e.title, c.course_name, COUNT(ea.attempt_id) as total_takers, AVG(ea.score) as average_score FROM exams e JOIN courses c ON e.course_id = c.course_id LEFT JOIN exam_attempts ea ON e.exam_id = ea.exam_id AND ea.status = 'finished' WHERE c.teacher_id = %s GROUP BY e.exam_id", (teacher_id,))
    exams = cursor.fetchall(); cursor.close(); connection.close()
    return render_template('teacher_analysis.html', exams=exams)

@teacher.route('/enroll_student', methods=['POST'])
def enroll_student():
    if teacher_logged_in():
        s_id = request.form.get('student_id'); c_id = request.form.get('course_id'); connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        try: cursor.execute("INSERT INTO enrollments (student_id, course_id) VALUES (%s, %s)", (s_id, c_id)); connection.commit(); flash('Enrolled.', 'success')
        finally: cursor.close(); connection.close()
        return redirect(url_for('teacher.manage_enrollees', course_id=c_id))
    return redirect(url_for('auth.login'))

@teacher.route('/unenroll_student/<int:enrollment_id>/<int:course_id>', methods=['POST'])
def unenroll_student(enrollment_id, course_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(); cursor.execute("DELETE FROM enrollments WHERE enrollment_id = %s", (enrollment_id,)); connection.commit(); cursor.close(); connection.close(); flash('Removed.', 'success')
        return redirect(url_for('teacher.manage_enrollees', course_id=course_id))
    return redirect(url_for('auth.login'))

@teacher.route('/delete_exam/<int:exam_id>', methods=['POST'])
def delete_exam(exam_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(); cursor.execute("DELETE FROM exams WHERE exam_id = %s", (exam_id,)); connection.commit(); cursor.close(); connection.close(); flash('Deleted.', 'success')
        return redirect(url_for('teacher.manage_exams'))