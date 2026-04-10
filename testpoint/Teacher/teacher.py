from flask import Blueprint, render_template, request, redirect, url_for, flash, session
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
            # Stats: Count My Courses
            cursor.execute("SELECT COUNT(*) as count FROM courses WHERE teacher_id = %s", (teacher_id,))
            course_count = cursor.fetchone()['count']
            
            # Stats: Count My Exams
            cursor.execute("""
                SELECT COUNT(*) as count FROM exams e 
                JOIN courses c ON e.course_id = c.course_id 
                WHERE c.teacher_id = %s
            """, (teacher_id,))
            exam_count = cursor.fetchone()['count']
            
            # Stats: Count Total Enrolled Students
            cursor.execute("""
                SELECT COUNT(DISTINCT e.student_id) as count FROM enrollments e
                JOIN courses c ON e.course_id = c.course_id
                WHERE c.teacher_id = %s
            """, (teacher_id,))
            student_count = cursor.fetchone()['count']

            # Stats: Count Active Examinees
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

#! 2. MY COURSES
@teacher.route('/my_courses')
def my_courses():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT c.*, (SELECT COUNT(*) FROM enrollments WHERE course_id = c.course_id) as student_count 
            FROM courses c WHERE teacher_id = %s
        """, (teacher_id,))
        courses = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('teacher_my_courses.html', courses=courses)
    return redirect(url_for('auth.login'))

#! 3. ENROLLEES
@teacher.route('/manage_enrollees/<int:course_id>')
def manage_enrollees(course_id):
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        # Validate course ownership
        cursor.execute("""
            SELECT * FROM courses 
            WHERE course_id = %s AND teacher_id = %s
        """, (course_id, teacher_id))
        course = cursor.fetchone()

        if not course:
            flash("Unauthorized access.", "danger")
            return redirect(url_for('teacher.my_courses'))

        # ✅ 1. GET CURRENTLY ENROLLED STUDENTS (FOR TABLE)
        cursor.execute("""
            SELECT 
                e.enrollment_id,
                s.student_id,
                s.firstname,
                s.lastname,
                u.email,
                e.enrolled_at
            FROM enrollments e
            JOIN students s ON e.student_id = s.student_id
            JOIN users u ON s.student_id = u.user_id
            WHERE e.course_id = %s
        """, (course_id,))
        enrollees = cursor.fetchall()

        # ✅ 2. GET AVAILABLE STUDENTS (NOT ENROLLED, VERIFIED ONLY)
        cursor.execute("""
            SELECT s.student_id, s.firstname, s.lastname
            FROM students s
            INNER JOIN users u ON s.student_id = u.user_id
            LEFT JOIN enrollments e 
                ON s.student_id = e.student_id AND e.course_id = %s
            WHERE u.is_verified = 1
            AND e.student_id IS NULL
        """, (course_id,))
        all_students = cursor.fetchall()

        cursor.close()
        connection.close()

        return render_template(
            'teacher_enrollees.html',
            course=course,
            enrollees=enrollees,
            all_students=all_students
        )

    return redirect(url_for('auth.login'))


#! 4. EXAMS
@teacher.route('/manage_exams')
def manage_exams():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT e.*, c.course_name, c.course_code 
            FROM exams e 
            JOIN courses c ON e.course_id = c.course_id 
            WHERE c.teacher_id = %s
        """, (teacher_id,))
        exams = cursor.fetchall()
        
        cursor.execute("SELECT course_id, course_name FROM courses WHERE teacher_id = %s", (teacher_id,))
        courses = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('teacher_exams.html', exams=exams, courses=courses)
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
            flash(f'Database Error: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()
        return redirect(url_for('teacher.manage_exams'))
    return redirect(url_for('auth.login'))

@teacher.route('/update_exam', methods=['POST'])
def update_exam():
    if teacher_logged_in():
        exam_id = request.form.get('exam_id')
        title = request.form.get('title')
        duration = request.form.get('duration')
        pass_percent = request.form.get('pass_percentage')

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("""
                UPDATE exams 
                SET title = %s, duration_minutes = %s, pass_percentage = %s 
                WHERE exam_id = %s
            """, (title, duration, pass_percent, exam_id))
            connection.commit()
            flash('Exam configuration updated successfully!', 'success')
        except mysql.connector.Error as err:
            flash(f'Error updating exam: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()
        return redirect(url_for('teacher.manage_exams'))
    return redirect(url_for('auth.login'))

#! 5. QUESTIONS (CENTRALIZED BANK LOGIC)
@teacher.route('/manage_questions/<int:exam_id>')
def manage_questions(exam_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        # 1. Get Exam and Course Details
        cursor.execute("SELECT * FROM exams WHERE exam_id = %s", (exam_id,))
        exam = cursor.fetchone()
        
        # 2. Get Questions currently linked to this exam via the junction table
        cursor.execute("""
            SELECT q.* FROM questions q
            JOIN exam_questions eq ON q.question_id = eq.question_id
            WHERE eq.exam_id = %s
        """, (exam_id,))
        questions = cursor.fetchall()
        
        # 3. Fetch options for each question
        for q in questions:
            cursor.execute("SELECT * FROM options WHERE question_id = %s", (q['question_id'],))
            q['options'] = cursor.fetchall()

        # 4. Optional: Fetch other questions from the Course Bank NOT in this exam
        # This allows teachers to "reuse" questions
        cursor.execute("""
            SELECT * FROM questions 
            WHERE course_id = %s AND question_id NOT IN (
                SELECT question_id FROM exam_questions WHERE exam_id = %s
            )
        """, (exam['course_id'], exam_id))
        bank_questions = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('teacher_questions.html', exam=exam, questions=questions, bank_questions=bank_questions)
    return redirect(url_for('auth.login'))

@teacher.route('/add_question/<int:exam_id>', methods=['POST'])
def add_question(exam_id):
    if teacher_logged_in():
        q_text = request.form.get('question_text')
        q_type = request.form.get('question_type')
        difficulty = request.form.get('difficulty')
        points = request.form.get('points')

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        try:
            # 1. Get the Course ID associated with this exam
            cursor.execute("SELECT course_id FROM exams WHERE exam_id = %s", (exam_id,))
            course_id = cursor.fetchone()['course_id']

            # 2. Insert into Centralized Bank (Questions table now uses course_id)
            cursor.execute("""
                INSERT INTO questions (course_id, question_text, question_type, difficulty, points)
                VALUES (%s, %s, %s, %s, %s)
            """, (course_id, q_text, q_type, difficulty, points))
            q_id = cursor.lastrowid

            # 3. Link this question to the current Exam
            cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id))

            # 4. Handle Options
            if q_type == 'multiple_choice':
                options = request.form.getlist('options[]')
                correct_idx = int(request.form.get('correct_option'))
                for i, opt_text in enumerate(options):
                    is_correct = 1 if i == correct_idx else 0
                    cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", 
                                   (q_id, opt_text, is_correct))
            
            elif q_type == 'true_false':
                correct_val = request.form.get('tf_correct')
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'True', 1 if correct_val == 'True' else 0))
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'False', 1 if correct_val == 'False' else 0))
            
            elif q_type == 'identification':
                answer = request.form.get('ident_answer')
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, answer, 1))

            connection.commit()
            flash('Question added to bank and linked to exam!', 'success')
        except mysql.connector.Error as err:
            flash(f'Error adding question: {err}', 'danger')
        finally:
            cursor.close()
            connection.close()
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))
    return redirect(url_for('auth.login'))

@teacher.route('/import_questions', methods=['POST'])
def import_questions():
    if not teacher_logged_in():
        return redirect(url_for('auth.login'))

    exam_id = request.form.get('exam_id')
    file = request.files.get('excel_file')
    connection = None
    cursor = None

    if not file or not file.filename.endswith(('.xlsx', '.xls')):
        flash('Invalid file format.', 'danger')
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

    try:
        df = pd.read_excel(file, engine='openpyxl')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        # Get course_id for the bank
        cursor.execute("SELECT course_id FROM exams WHERE exam_id = %s", (exam_id,))
        course_id = cursor.fetchone()['course_id']

        for _, row in df.iterrows():
            cursor.execute("""
                INSERT INTO questions (course_id, question_text, question_type, difficulty, points)
                VALUES (%s, %s, %s, %s, %s)
            """, (course_id, row['Question'], row['Type'], row['Difficulty'], row['Points']))
            
            q_id = cursor.lastrowid
            # Link to junction table
            cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id))
            
            q_type = str(row['Type']).lower().strip()
            correct_answer = str(row['Answer']).strip()

            if q_type == 'multiple_choice':
                options_list = [str(row['OptA']), str(row['OptB']), str(row['OptC']), str(row['OptD'])]
                for opt_text in options_list:
                    is_correct = 1 if opt_text.strip() == correct_answer else 0
                    cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, opt_text, is_correct))
            elif q_type == 'true_false':
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'True', 1 if correct_answer.lower() == 'true' else 0))
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'False', 1 if correct_answer.lower() == 'false' else 0))
            elif q_type == 'identification':
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, correct_answer, 1))

        connection.commit()
        flash('Bulk question import successful!', 'success')
    except Exception as e:
        if connection: connection.rollback()
        flash(f'Import Error: {str(e)}', 'danger')
    finally:
        if cursor: cursor.close()
        if connection: connection.close()
    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

@teacher.route('/link_from_bank/<int:exam_id>/<int:q_id>', methods=['POST'])
def link_from_bank(exam_id, q_id):
    """New route to link an existing bank question to an exam"""
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id))
            connection.commit()
            flash('Question added from bank!', 'success')
        except:
            flash('Question already in this exam.', 'warning')
        finally:
            cursor.close()
            connection.close()
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

@teacher.route('/delete_question/<int:q_id>/<int:exam_id>', methods=['POST'])
def delete_question(q_id, exam_id):
    """Modified: Removes the link to the exam, but keeps it in the Course Bank"""
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        # Only remove the link from the junction table
        cursor.execute("DELETE FROM exam_questions WHERE question_id = %s AND exam_id = %s", (q_id, exam_id))
        connection.commit()
        cursor.close()
        connection.close()
        flash('Question removed from this exam (it remains in your bank).', 'success')
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

#! 6. MONITORING & ANALYSIS
@teacher.route('/student_monitor')
def student_monitor():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT ea.*, s.firstname, s.lastname, ex.title
            FROM exam_attempts ea
            JOIN students s ON ea.student_id = s.student_id
            JOIN exams ex ON ea.exam_id = ex.exam_id
            JOIN courses c ON ex.course_id = c.course_id
            WHERE c.teacher_id = %s AND ea.status = 'in-progress'
        """, (teacher_id,))
        attempts = cursor.fetchall()
        cursor.close()
        connection.close()
        return render_template('teacher_monitor.html', attempts=attempts)
    return redirect(url_for('auth.login'))

@teacher.route('/item_analysis')
def item_analysis():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        # Updated to account for the course-level bank via junction
        cursor.execute("""
            SELECT q.question_text, q.question_type, 
            COUNT(sa.answer_id) as total_attempts,
            SUM(CASE WHEN sa.is_correct = 0 THEN 1 ELSE 0 END) as fail_count
            FROM student_answers sa
            JOIN questions q ON sa.question_id = q.question_id
            JOIN courses c ON q.course_id = c.course_id
            WHERE c.teacher_id = %s 
            GROUP BY q.question_id
        """, (teacher_id,))
        analytics = cursor.fetchall()
        cursor.close()
        connection.close()
        return render_template('teacher_analysis.html', analytics=analytics)
    return redirect(url_for('auth.login'))

#! 7. ENROLLMENT HELPERS (UNTOUCHED)
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
            flash('Student enrolled.', 'success')
        except:
            flash('Already enrolled.', 'warning')
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

@teacher.route('/delete_exam/<int:exam_id>', methods=['POST'])
def delete_exam(exam_id):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("DELETE FROM exams WHERE exam_id = %s", (exam_id,))
        connection.commit()
        cursor.close()
        connection.close()
        flash('Exam deleted. Questions remain in bank.', 'success')
    return redirect(url_for('teacher.manage_exams'))