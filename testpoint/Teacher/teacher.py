from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from testpoint import db_config
from testpoint.Auth.login import teacher_logged_in
import mysql.connector
import pandas as pd 
import io
from datetime import datetime
from werkzeug.security import generate_password_hash


teacher = Blueprint('teacher', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/teacher/static')

#! 1. DASHBOARD
@teacher.route('/')
def teacher_dashboard():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        try:
            # 1. Summary Card Stats
            cursor.execute("SELECT COUNT(*) as count FROM courses WHERE teacher_id = %s", (teacher_id,))
            course_count = cursor.fetchone()['count']
            
            cursor.execute("""
                SELECT COUNT(*) as count FROM exam_attempts ea 
                JOIN exams ex ON ea.exam_id = ex.exam_id 
                JOIN courses c ON ex.course_id = c.course_id 
                WHERE c.teacher_id = %s AND ea.status = 'in-progress'
            """, (teacher_id,))
            active_examinees = cursor.fetchone()['count']

            cursor.execute("""
                SELECT COUNT(*) as count FROM questions q 
                JOIN courses c ON q.course_id = c.course_id 
                WHERE c.teacher_id = %s
            """, (teacher_id,))
            bank_count = cursor.fetchone()['count']

            cursor.execute("""
                SELECT SUM(ea.tab_switches) as total FROM exam_attempts ea 
                JOIN exams ex ON ea.exam_id = ex.exam_id 
                JOIN courses c ON ex.course_id = c.course_id 
                WHERE c.teacher_id = %s
            """, (teacher_id,))
            total_violations = cursor.fetchone()['total'] or 0

            # 2. Performance Metric
            cursor.execute("""
                SELECT AVG((ea.score / (SELECT COUNT(*) FROM exam_questions WHERE exam_id = ea.exam_id)) * 100) as avg_score
                FROM exam_attempts ea
                JOIN exams ex ON ea.exam_id = ex.exam_id
                JOIN courses c ON ex.course_id = c.course_id
                WHERE c.teacher_id = %s AND ea.status = 'finished'
            """, (teacher_id,))
            class_avg = cursor.fetchone()['avg_score'] or 0

            # 3. Question Bank Distribution (FOR THE CHART)
            cursor.execute("""
                SELECT question_type, COUNT(*) as count FROM questions q 
                JOIN courses c ON q.course_id = c.course_id 
                WHERE c.teacher_id = %s GROUP BY question_type
            """, (teacher_id,))
            dist_data = cursor.fetchall()
            
            # Map database keys to human-readable labels
            type_mapping = {
                'multiple_choice': 'MCQ',
                'true_false': 'T/F',
                'identification': 'Ident.',
                'essay': 'Essay'
            }
            dist_labels = [type_mapping.get(d['question_type'], d['question_type']) for d in dist_data]
            dist_values = [int(d['count']) for d in dist_data]

            # 4. REPLACEMENT: Recent Exam Activity (Last 5 finished exams)
            cursor.execute("""
                SELECT ea.score, s.firstname, s.lastname, ex.title, ea.end_time,
                (SELECT question_limit FROM exams WHERE exam_id = ea.exam_id) as total_q
                FROM exam_attempts ea
                JOIN students s ON ea.student_id = s.student_id
                JOIN exams ex ON ea.exam_id = ex.exam_id
                JOIN courses c ON ex.course_id = c.course_id
                WHERE c.teacher_id = %s AND ea.status = 'finished'
                ORDER BY ea.end_time DESC LIMIT 5
            """, (teacher_id,))
            
            recent_submissions = cursor.fetchall()

            return render_template('teacher_dashboard.html',
                                   firstname=session.get('firstname'), 
                                   active_examinees=active_examinees,
                                   bank_count=bank_count,
                                   total_violations=total_violations,
                                   class_avg=round(class_avg, 1),
                                   dist_labels=dist_labels,
                                   dist_values=dist_values,
                                   recent_submissions=recent_submissions)
        finally:
            cursor.close()
            connection.close()
    return redirect(url_for('auth.login'))

#! 2. QUESTION BANK (Grouping by Course)
@teacher.route('/question_bank')
def question_bank():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

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
        
        cursor.execute("SELECT * FROM courses WHERE course_id = %s AND teacher_id = %s", (course_id, teacher_id))
        course = cursor.fetchone()
        if not course:
            flash("Unauthorized access.", "danger")
            return redirect(url_for('teacher.question_bank'))

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
        cursor.execute("DELETE FROM questions WHERE question_id = %s", (q_id,))
        connection.commit()
        cursor.close()
        connection.close()
        flash('Question permanently deleted from Bank.', 'success')
        return redirect(url_for('teacher.course_question_bank', course_id=course_id))
    
@teacher.route('/bulk_delete_bank_questions/<int:course_id>', methods=['POST'])
def bulk_delete_bank_questions(course_id):
    if teacher_logged_in():
        question_ids = request.form.getlist('question_ids[]')
        
        if not question_ids:
            flash("No questions selected.", "warning")
            return redirect(url_for('teacher.course_question_bank', course_id=course_id))

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
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
        cursor.execute("SELECT e.enrollment_id, s.student_id, s.firstname, s.lastname, u.email, e.enrolled_at FROM enrollments e JOIN students s ON e.student_id = s.student_id JOIN users u ON s.student_id = u.user_id WHERE e.course_id = %s AND u.is_verified = 1  AND u.is_active = 1", (course_id,))
        enrollees = cursor.fetchall()
        cursor.execute("SELECT s.student_id, s.firstname, s.lastname FROM students s INNER JOIN users u ON s.student_id = u.user_id LEFT JOIN enrollments e ON s.student_id = e.student_id AND e.course_id = %s WHERE u.is_verified = 1 AND e.student_id IS NULL AND u.is_active = 1", (course_id,))
        all_students = cursor.fetchall()
        cursor.close()
        connection.close()
        return render_template('teacher_enrollees.html', course=course, enrollees=enrollees, all_students=all_students)
    return redirect(url_for('auth.login'))

@teacher.route('/bulk_enroll_students', methods=['POST'])
def bulk_enroll_students():
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    course_id = request.form.get('course_id')
    student_ids = request.form.getlist('student_ids[]')

    if not student_ids:
        flash("No students selected for enrollment.", "warning")
        return redirect(url_for('teacher.manage_enrollees', course_id=course_id))

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    try:
        for s_id in student_ids:
            cursor.execute("INSERT IGNORE INTO enrollments (student_id, course_id) VALUES (%s, %s)", (s_id, course_id))
        
        connection.commit()
        flash(f'Successfully enrolled {len(student_ids)} students.', 'success')
    except mysql.connector.Error as err:
        flash(f'Error: {err}', 'danger')
    finally:
        cursor.close()
        connection.close()

    return redirect(url_for('teacher.manage_enrollees', course_id=course_id))

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

@teacher.route('/manage_exams')
def manage_exams():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
   
        cursor.execute("""
            SELECT e.*, c.course_name, c.course_code, e.date_time,
            (SELECT COUNT(*) FROM exam_questions WHERE exam_id = e.exam_id) as q_count
            FROM exams e 
            JOIN courses c ON e.course_id = c.course_id 
            WHERE c.teacher_id = %s AND e.archived = 0
        """, (teacher_id,))
        exams = cursor.fetchall()

        cursor.execute("SELECT course_id, course_name FROM courses WHERE teacher_id = %s", (teacher_id,))
        courses = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('teacher_exams.html', exams=exams, courses=courses, now=datetime.now())
    return redirect(url_for('auth.login'))

#! 4. EXAMS (Modified for Question Limit)
@teacher.route('/add_exam', methods=['POST'])
def add_exam():
    if teacher_logged_in():
        course_id = request.form.get('course_id')
        title = request.form.get('title')
        duration = request.form.get('duration')
        pass_percent = request.form.get('pass_percentage')
        schedule = request.form.get('schedule')
        q_limit = request.form.get('question_limit', 50)
        teacher_id = session.get('user_id')

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("""
                INSERT INTO exams (course_id, title, duration_minutes, pass_percentage, date_time, created_by, question_limit, is_active) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
            """, (course_id, title, duration, pass_percent, schedule, teacher_id, q_limit))
            new_id = cursor.lastrowid
            connection.commit()
            flash('Exam initialized! Now add questions to the pool.', 'success')
            return redirect(url_for('teacher.manage_questions', exam_id=new_id)) 
        except mysql.connector.Error as err:
            flash(f'Error: {err}', 'danger')
            return redirect(url_for('teacher.manage_exams'))
        finally:
            cursor.close()
            connection.close()
    return redirect(url_for('auth.login'))

@teacher.route('/update_exam', methods=['POST'])
def update_exam():
    if not teacher_logged_in():
        return redirect(url_for('auth.login'))

    exam_id = request.form.get('exam_id')
    status = request.form.get('status')
    title = request.form.get('title')
    duration = request.form.get('duration')
    pass_percent = request.form.get('pass_percentage')
    schedule = request.form.get('schedule')
    q_limit = request.form.get('question_limit')

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)

    try:
        # Check if the teacher is attempting to ACTIVATE the exam
        if status == 'active':
            cursor.execute("SELECT COUNT(*) as count FROM exam_questions WHERE exam_id = %s", (exam_id,))
            number_of_questions = cursor.fetchone()['count']

            # Check 1: Pool is empty
            if number_of_questions == 0:
                flash("Cannot activate an empty exam. Link questions to the pool first.", "danger")
                return redirect(url_for('teacher.manage_exams'))

            # Check 2: Pool is smaller than the limit
            if int(q_limit) > int(number_of_questions):
                flash(f"Cannot activate. You only have {number_of_questions} questions in the pool, but the limit is set to {q_limit}.", "danger")
                return redirect(url_for('teacher.manage_exams'))

            # Check 3: Limit is invalid
            if int(q_limit) <= 0:
                flash("Question limit must be at least 1 to activate the exam.", "danger")
                return redirect(url_for('teacher.manage_exams'))

            # If it's not 'active' or all checks passed, update the DB
        status_int = 1 if status == 'active' else 0
        cursor.execute("""
            UPDATE exams 
            SET title = %s, duration_minutes = %s, pass_percentage = %s,
                is_active = %s, date_time = %s, question_limit = %s 
            WHERE exam_id = %s
        """, (title, duration, pass_percent, status_int, schedule, q_limit, exam_id))       

        connection.commit()
        flash('Exam configuration updated successfully!', 'success')

    except mysql.connector.Error as err:
        flash(f"Database error: {err}", "danger")
    finally:
        cursor.close()
        connection.close()

    return redirect(url_for('teacher.manage_exams'))

@teacher.route('/delete_exam/<int:exam_id>', methods=['POST'])
def delete_exam(exam_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("UPDATE exams SET archived = 1 WHERE exam_id = %s", (exam_id,)); 
        connection.commit()
        cursor.close()
        connection.close()
        flash('Deleted.', 'success')
        return redirect(url_for('teacher.manage_exams'))
    
#! 9. TRASH BIN LOGIC (Using 'archived' column)
@teacher.route('/trashed_exams')
def trashed_exams():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT e.*, c.course_name, c.course_code FROM exams e 
            JOIN courses c ON e.course_id = c.course_id 
            WHERE e.created_by = %s AND e.archived = 1
        """, (teacher_id,))
        exams = cursor.fetchall()
        cursor.close(); connection.close()
        return render_template('teacher_trashed_exams.html', exams=exams)
    return redirect(url_for('auth.login'))

@teacher.route('/soft_delete_exam/<int:exam_id>', methods=['POST'])
def soft_delete_exam(exam_id):
    """Moves exam to trash by setting archived = 1"""
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    try:
        cursor.execute("UPDATE exams SET archived = 1 WHERE exam_id = %s", (exam_id,))
        connection.commit()
        flash('Exam moved to trash bin.', 'warning')
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for('teacher.manage_exams'))

@teacher.route('/restore_exam/<int:exam_id>', methods=['POST'])
def restore_exam(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    try:
        cursor.execute("UPDATE exams SET archived = 0 WHERE exam_id = %s", (exam_id,))
        connection.commit()
        flash('Exam restored successfully!', 'success')
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for('teacher.trashed_exams'))

@teacher.route('/delete_exam_permanently/<int:exam_id>', methods=['POST'])
def delete_exam_permanently(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM exams WHERE exam_id = %s", (exam_id,))
        connection.commit()
        flash('Exam permanently erased.', 'success')
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for('teacher.trashed_exams'))

@teacher.route('/empty_exam_trash', methods=['POST'])
def empty_exam_trash():
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    teacher_id = session.get('user_id')
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM exams WHERE created_by = %s AND archived = 1", (teacher_id,))
        connection.commit()
        flash('Trash bin emptied successfully.', 'success')
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for('teacher.trashed_exams'))

@teacher.route('/teacher_review/<int:attempt_id>')
def teacher_review(attempt_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True, buffered=True)

    # Fetch questions Served during this specific attempt
    cursor.execute("""
        SELECT q.*, sa.submitted_answer, sa.is_correct
        FROM questions q
        JOIN attempt_questions aq ON q.question_id = aq.question_id
        LEFT JOIN student_answers sa ON q.question_id = sa.question_id AND sa.attempt_id = %s
        WHERE aq.attempt_id = %s
    """, (attempt_id, attempt_id))
    review_data = cursor.fetchall()

    for q in review_data:
        # Load options and identify which one was correct
        cursor.execute("SELECT * FROM options WHERE question_id = %s", (q['question_id'],))
        q['options'] = cursor.fetchall()

    cursor.close()
    connection.close()
    return render_template('teacher_review_attempt.html', review_data=review_data)

@teacher.route('/review_student_attempt/<int:attempt_id>')
def review_student_attempt(attempt_id):
    if not teacher_logged_in(): 
        return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    # Ensure buffered=True is used to prevent "Unread result" errors
    cursor = connection.cursor(dictionary=True, buffered=True)

    try:
        # 1. FETCH ATTEMPT, STUDENT, AND EXAM DATA (Added e.pass_percentage)
        cursor.execute("""
            SELECT 
                ea.*, 
                s.firstname, s.lastname, 
                e.title, e.pass_percentage, 
                c.course_name
            FROM exam_attempts ea
            JOIN students s ON ea.student_id = s.student_id
            JOIN exams e ON ea.exam_id = e.exam_id
            JOIN courses c ON e.course_id = c.course_id
            WHERE ea.attempt_id = %s
        """, (attempt_id,))
        attempt = cursor.fetchone()

        if not attempt:
            flash("Attempt records not found.", "danger")
            return redirect(url_for('teacher.manage_exams'))

        # 2. FETCH THE QUESTIONS SERVED
        cursor.execute("""
            SELECT q.*, sa.submitted_answer, sa.is_correct
            FROM questions q
            JOIN attempt_questions aq ON q.question_id = aq.question_id
            LEFT JOIN student_answers sa ON q.question_id = sa.question_id AND sa.attempt_id = %s
            WHERE aq.attempt_id = %s
        """, (attempt_id, attempt_id))
        review_questions = cursor.fetchall()

        # 3. FETCH OPTIONS FOR EACH QUESTION
        for q in review_questions:
            cursor.execute("SELECT * FROM options WHERE question_id = %s", (q['question_id'],))
            q['options'] = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Database Error: {err}", "danger")
        return redirect(url_for('teacher.manage_exams'))
    finally:
        cursor.close()
        connection.close()

    return render_template('teacher_review_attempt.html', attempt=attempt, questions=review_questions)

#! MANAGE QUESTIONS
@teacher.route('/manage_questions/<int:exam_id>')
def manage_questions(exam_id):
    if not teacher_logged_in(): 
        return redirect(url_for('auth.login'))

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True, buffered=True)
    
    try:
        cursor.execute("SELECT * FROM exams WHERE exam_id = %s", (exam_id,))
        exam = cursor.fetchone()

        if not exam:
            flash("Exam not found or has been deleted.", "danger")
            return redirect(url_for('teacher.manage_exams'))

        cursor.execute("""
            SELECT q.* FROM questions q
            JOIN exam_questions eq ON q.question_id = eq.question_id
            WHERE eq.exam_id = %s
            ORDER BY FIELD(q.difficulty, 'easy', 'medium', 'hard'), q.question_id DESC
        """, (exam_id,))
        questions = cursor.fetchall()
      
        for q in questions:
            cursor.execute("SELECT * FROM options WHERE question_id = %s", (q['question_id'],))
            q['options'] = cursor.fetchall()
            
        cursor.execute("""
            SELECT * FROM questions 
            WHERE course_id = %s AND question_id NOT IN (
                SELECT question_id FROM exam_questions WHERE exam_id = %s
            )
            ORDER BY 
                FIELD(difficulty, 'easy', 'medium', 'hard') ASC,
                FIELD(question_type, 'multiple_choice', 'true_false', 'identification') ASC
        """, (exam['course_id'], exam_id))
        bank_questions = cursor.fetchall()
        
        for bq in bank_questions:
            cursor.execute("SELECT * FROM options WHERE question_id = %s", (bq['question_id'],))
            bq['options'] = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Database Error: {err}", "danger")
        questions = []
        bank_questions = []
        exam = None
    finally:
        if cursor: cursor.close()
        if connection: connection.close()
        
    return render_template('teacher_questions.html', 
                           exam=exam, 
                           questions=questions, 
                           bank_questions=bank_questions)

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
    if not teacher_logged_in():
        return redirect(url_for('auth.login'))

    exam_id = request.form.get('exam_id')
    course_id = request.form.get('course_id')
    file = request.files.get('excel_file')
    
    connection = None
    cursor = None

    if not file or not file.filename.endswith(('.xlsx', '.xls')):
        flash('Invalid file format. Please upload an .xlsx file.', 'danger')
        return redirect(request.referrer)

    try:
        # 1. Load Excel
        df = pd.read_excel(file, engine='openpyxl')
        
        connection = mysql.connector.connect(**db_config)
        # Use buffered to handle multiple queries in the loop
        cursor = connection.cursor(dictionary=True, buffered=True)

        # 2. Logic Check: Determine target Course
        # If we have an exam_id, we look up its course. If not, we use course_id directly.
        target_course_id = course_id
        if exam_id and int(exam_id) != 0:
            cursor.execute("SELECT course_id FROM exams WHERE exam_id = %s", (exam_id,))
            exam_row = cursor.fetchone()
            if exam_row:
                target_course_id = exam_row['course_id']

        # 3. Process Rows
        for _, row in df.iterrows():
            # A. Insert into Master 'questions' table
            cursor.execute("""
                INSERT INTO questions (course_id, question_text, question_type, difficulty)
                VALUES (%s, %s, %s, %s)
            """, (target_course_id, row['Question'], row['Type'], row['Difficulty']))
            
            q_id = cursor.lastrowid
            
            # B. LINK TO EXAM ONLY IF EXAM_ID IS NOT 0
            if exam_id and int(exam_id) != 0:
                cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id))
            
            # C. Insert Options
            q_type = str(row['Type']).lower().strip()
            correct_ans = str(row['Answer']).strip()

            if q_type == 'multiple_choice':
                opts = [str(row['OptA']), str(row['OptB']), str(row['OptC']), str(row['OptD'])]
                for opt_text in opts:
                    is_correct = 1 if opt_text.strip() == correct_ans else 0
                    cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", 
                                   (q_id, opt_text, is_correct))
            elif q_type == 'true_false':
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", 
                               (q_id, 'True', 1 if correct_ans.lower() == 'true' else 0))
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", 
                               (q_id, 'False', 1 if correct_ans.lower() == 'false' else 0))
            elif q_type == 'identification':
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", 
                               (q_id, correct_ans, 1))

        connection.commit()
        flash('Import successful!', 'success')
        
    except Exception as e:
        if connection: connection.rollback()
        flash(f'Import Error: {str(e)}', 'danger')
    finally:
        if cursor: cursor.close()
        if connection: connection.close()

    return redirect(request.referrer)

@teacher.route('/link_from_bank/<int:exam_id>/<int:q_id>', methods=['POST'])
def link_from_bank(exam_id, q_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        try: cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id)); connection.commit(); flash('Linked!', 'success')
        except: flash('Already in exam.', 'warning')
        finally: cursor.close(); connection.close()
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))
    
@teacher.route('/bulk_link_from_bank/<int:exam_id>', methods=['POST'])
def bulk_link_from_bank(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    q_ids = request.form.getlist('bank_q_ids[]')
    
    if not q_ids:
        flash("No questions were selected from the bank.", "warning")
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    try:
        for q_id in q_ids:
            cursor.execute("INSERT IGNORE INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id))
        
        connection.commit()
        flash(f"Successfully linked {len(q_ids)} questions to the exam.", "success")
    except mysql.connector.Error as err:
        flash(f"Database Error: {err}", "danger")
    finally:
        cursor.close()
        connection.close()
        
    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

@teacher.route('/bulk_unlink_questions/<int:exam_id>', methods=['POST'])
def bulk_unlink_questions(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    q_ids = request.form.getlist('question_ids[]')
    
    if not q_ids:
        flash("No questions selected.", "warning")
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    try:
        # Construct the SQL to remove only the links for selected questions in this exam
        format_strings = ','.join(['%s'] * len(q_ids))
        query = f"DELETE FROM exam_questions WHERE exam_id = %s AND question_id IN ({format_strings})"
        cursor.execute(query, [exam_id] + q_ids)
        connection.commit()
        flash(f"Successfully unlinked {len(q_ids)} questions.", "success")
    except mysql.connector.Error as err:
        flash(f"Error: {err}", "danger")
    finally:
        cursor.close()
        connection.close()
        
    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

#! 5. QUESTIONS - DELETE/UNLINK
@teacher.route('/delete_question/<int:q_id>/<int:exam_id>', methods=['POST'])
def delete_question(q_id, exam_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("DELETE FROM exam_questions WHERE question_id = %s AND exam_id = %s", (q_id, exam_id))
        
        cursor.execute("SELECT COUNT(*) as count FROM exam_questions WHERE exam_id = %s", (exam_id,))
        if cursor.fetchone()['count'] == 0:

            cursor.execute("UPDATE exams SET is_active = 0 WHERE exam_id = %s", (exam_id,))
            flash('Question unlinked. Exam set to INACTIVE because it is now empty.', 'warning')
        else:
            flash('Question unlinked.', 'success')

        connection.commit()
        cursor.close()
        connection.close()
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

#! 6. TEACHER PROFILE MANAGEMENT
@teacher.route('/profile', methods=['GET', 'POST'])
def profile():
    if not teacher_logged_in():
        flash('Please log in as a teacher to access the profile.', 'danger')
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

            # Update Teacher specific info
            cursor.execute("""
                UPDATE teachers 
                SET firstname = %s, middlename = %s, lastname = %s 
                WHERE teacher_id = %s
            """, (firstname, middlename, lastname, user_id))

            # Handle Password Update
            if new_password:
                if new_password == confirm_password:
                    hashed_pw = generate_password_hash(new_password)
                    cursor.execute(
                        "UPDATE users SET password = %s WHERE user_id = %s",
                        (hashed_pw, user_id)
                    )
                    # Sync session names
                    session['firstname'] = firstname
                    session['lastname'] = lastname
                else:
                    connection.rollback()
                    flash('Passwords do not match.', 'warning')
                    return redirect(url_for('teacher.profile'))

            connection.commit()
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('teacher.profile'))

        # GET: Fetch Teacher Data
        cursor.execute("""
            SELECT u.user_id, u.email, u.role, u.created_at,
                   t.firstname, t.middlename, t.lastname,
                   t.region, t.province, t.city, t.barangay
            FROM users u
            JOIN teachers t ON u.user_id = t.teacher_id
            WHERE u.user_id = %s
        """, (user_id,))
        user_data = cursor.fetchone()

        return render_template('teacher_profile.html', user=user_data)

    except mysql.connector.Error as err:
        connection.rollback()
        flash(f'Database Error: {err}', 'danger')
        return redirect(url_for('teacher.profile'))

    finally:
        cursor.close()
        connection.close()
