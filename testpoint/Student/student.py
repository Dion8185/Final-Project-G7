from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
import mysql.connector
from testpoint import db_config
from testpoint.Auth.login import user_logged_in
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta

student = Blueprint('student', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/student/static')

@student.before_app_request
def enforce_lockdown():
    active_exam_id = session.get('active_exam_id')
    if active_exam_id:
        allowed_endpoints = [
            'student.take_exam', 
            'student.save_progress', 
            'student.log_violation', 
            'student.submit_exam',
            'auth.logout', 
            'static'
        ]
        if request.endpoint and request.endpoint not in allowed_endpoints:
            return redirect(url_for('student.take_exam', exam_id=active_exam_id))

@student.app_context_processor
def inject_enrolled_courses():
    if 'user_id' in session and session.get('role') == 'student':
        student_id = session.get('user_id')
        
        try:
            connection = mysql.connector.connect(**db_config)
            cursor = connection.cursor(dictionary=True)
            
            # Query all courses the student is enrolled in
            cursor.execute("""
                SELECT c.course_id, c.course_name, c.course_code 
                FROM courses c
                JOIN enrollments e ON c.course_id = e.course_id
                WHERE e.student_id = %s
            """, (student_id,))
            courses = cursor.fetchall()
            
            cursor.close()
            connection.close()
            return dict(enrolled_courses=courses)
        except Exception as e:
            print(f"DEBUG ERROR: {e}") # This will show in your terminal
            return dict(enrolled_courses=[])
    return dict(enrolled_courses=[])

#! 1. DASHBOARD
@student.route('/student_dashboard')
def student_dashboard():
    if user_logged_in():
        student_id = session.get('user_id')
        student_firstname = session.get('firstname')
        student_lastname = session.get('lastname')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        try:
            # Stats 1: Enrolled Courses
            cursor.execute("SELECT COUNT(*) as count FROM enrollments WHERE student_id = %s", (student_id,))
            course_count = cursor.fetchone()['count']

            # Stats 2: Completed Exams (exclude archived exams)
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM exam_attempts ea
                JOIN exams e ON ea.exam_id = e.exam_id
                WHERE ea.student_id = %s
                AND ea.status = 'finished'
                AND e.archived = 0
            """, (student_id,))
            completed_count = cursor.fetchone()['count']
            
            # Stats 3: Available Exams (Active exams in enrolled courses not yet finished)
            cursor.execute("""
                SELECT COUNT(*) as count FROM exams e
                JOIN enrollments en ON e.course_id = en.course_id
                LEFT JOIN exam_attempts ea ON e.exam_id = ea.exam_id AND ea.student_id = %s
                WHERE en.student_id = %s AND e.is_active = 1 AND (ea.status IS NULL OR ea.status = 'in-progress') AND e.archived = 0;
            """, (student_id, student_id))
            available_count = cursor.fetchone()['count']

            return render_template('student_dashboard.html', 
                                   course_count=course_count, 
                                   completed_count=completed_count, 
                                   available_count=available_count,
                                   student_firstname=student_firstname,
                                   student_lastname = student_lastname
                                   )
        finally:
            cursor.close()
            connection.close()
    
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

#! 2. AVAILABLE EXAMS
@student.route('/student_exams')
def student_exams():
    if user_logged_in():
        student_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT e.*, c.course_name, c.course_code, ea.status as attempt_status
            FROM exams e
            JOIN courses c ON e.course_id = c.course_id
            JOIN enrollments en ON e.course_id = en.course_id
            LEFT JOIN exam_attempts ea ON e.exam_id = ea.exam_id AND ea.student_id = %s
            WHERE en.student_id = %s AND e.archived = 0;
        """, (student_id, student_id))
        exams = cursor.fetchall()
        
        now = datetime.now()
        
        for exam in exams:
            start_time = exam['date_time']
            end_time = start_time + timedelta(minutes=exam['duration_minutes'])
            
            exam['status_label'] = "Available"
            exam['status_class'] = "primary"
            exam['can_start'] = False

            if exam['attempt_status'] == 'finished':
                exam['status_label'] = "Completed"
                exam['status_class'] = "success"
            elif exam['is_active'] == 0:
                exam['status_label'] = "Unavailable"
                exam['status_class'] = "secondary"
            elif now < start_time:
                exam['status_label'] = "Upcoming"
                exam['status_class'] = "warning"
            elif now > end_time:
                exam['status_label'] = "Expired"
                exam['status_class'] = "danger"
            else:
                exam['status_label'] = "Ongoing"
                exam['status_class'] = "success"
                exam['can_start'] = True

        cursor.close()
        connection.close()
        return render_template('student_exams.html', exams=exams)
    return redirect(url_for('auth.login'))

#! 1. SAVE PROGRESS (AJAX)
@student.route('/save_progress', methods=['POST'])
def save_progress():
    data = request.get_json()
    attempt_id = data.get('attempt_id')
    q_id = data.get('question_id')
    ans = data.get('answer', "")
    is_flagged = data.get('is_flagged', 0)
    current_idx = data.get('current_idx', 0)

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    try:
        cursor.execute("""
            INSERT INTO student_answers (attempt_id, question_id, submitted_answer, is_flagged)
            VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE submitted_answer = %s, is_flagged = %s
        """, (attempt_id, q_id, ans, is_flagged, ans, is_flagged))
        
        cursor.execute("UPDATE exam_attempts SET current_q_index = %s WHERE attempt_id = %s", (current_idx, attempt_id))
        connection.commit()
    finally:
        cursor.close()
        connection.close()
    return jsonify({"status": "saved"})

#! 2. TAKE EXAM (PERSISTENT LOGIC)
@student.route('/take_exam/<int:exam_id>')
def take_exam(exam_id):
    if not user_logged_in(): return redirect(url_for('auth.login'))
    student_id = session.get('user_id')
    
    connection = mysql.connector.connect(**db_config)
    # Use buffered=True to avoid "Unread Result" errors during the loop
    cursor = connection.cursor(dictionary=True, buffered=True)

    # 1. Fetch Exam Meta & Timer Info
    cursor.execute("""
        SELECT *, TIMESTAMPDIFF(SECOND, NOW(), DATE_ADD(date_time, INTERVAL duration_minutes MINUTE)) as rem 
        FROM exams WHERE exam_id = %s
    """, (exam_id,))
    exam = cursor.fetchone()
    
    if not exam or exam['rem'] <= 0:
        session.pop('active_exam_id', None) 
        flash("Exam session has ended or not found.", "danger")
        return redirect(url_for('student.student_exams'))

    # 2. Check for existing Attempt
    cursor.execute("SELECT * FROM exam_attempts WHERE student_id = %s AND exam_id = %s", (student_id, exam_id))
    attempt = cursor.fetchone()

    if not attempt:
        # --- FIRST TIME STARTING ---
        cursor.execute("INSERT INTO exam_attempts (student_id, exam_id, status, start_time) VALUES (%s, %s, 'in-progress', NOW())", (student_id, exam_id))
        connection.commit()
        attempt_id = cursor.lastrowid
        
        # Pick the randomized subset from the total pool and save them to attempt_questions
        cursor.execute("""
            INSERT INTO attempt_questions (attempt_id, question_id)
            SELECT %s, question_id FROM exam_questions 
            WHERE exam_id = %s 
            ORDER BY RAND() 
            LIMIT %s
        """, (attempt_id, exam_id, exam['question_limit']))
        connection.commit()
        current_q = 0
        tab_switches = 0
    else:
        # --- RELOADING EXISTING EXAM ---
        if attempt['status'] == 'finished':
            session.pop('active_exam_id', None)
            return redirect(url_for('student.student_exams'))
        
        attempt_id = attempt['attempt_id']
        current_q = attempt['current_q_index']
        tab_switches = attempt['tab_switches']

    # 3. LOCK SESSION
    session['active_exam_id'] = exam_id

    # 4. LOAD THE QUESTIONS SERVED FOR THIS ATTEMPT
    cursor.execute("""
        SELECT q.* FROM questions q
        JOIN attempt_questions aq ON q.question_id = aq.question_id
        WHERE aq.attempt_id = %s
        ORDER BY FIELD(q.difficulty, 'easy', 'medium', 'hard')
    """, (attempt_id,))
    questions = cursor.fetchall()

    # 5. THE MISSING PART: Load Options and Saved Progress for every question
    for q in questions:
        # Fetch the multiple choice/true-false options
        cursor.execute("SELECT * FROM options WHERE question_id = %s", (q['question_id'],))
        q['options'] = cursor.fetchall() # <--- This makes choices visible!
        
        # Fetch any answer the student already saved (for persistence)
        cursor.execute("SELECT submitted_answer, is_flagged FROM student_answers WHERE attempt_id = %s AND question_id = %s", (attempt_id, q['question_id']))
        ans = cursor.fetchone()
        q['saved_answer'] = ans['submitted_answer'] if ans else ""
        q['is_flagged'] = ans['is_flagged'] if ans else 0

    cursor.close()
    connection.close()
    
    return render_template('take_exam.html', 
                           exam=exam, 
                           questions=questions, 
                           attempt_id=attempt_id, 
                           remaining_seconds=exam['rem'], 
                           current_q=current_q, 
                           tab_switches=tab_switches)

@student.route('/review_results/<int:attempt_id>')
def review_results(attempt_id):
    if not user_logged_in(): return redirect(url_for('auth.login'))
    
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
    return render_template('student_review.html', review_data=review_data)

@student.route('/review_exam/<int:attempt_id>')
def review_exam(attempt_id):
    if not user_logged_in(): return redirect(url_for('auth.login'))
    student_id = session.get('user_id')
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True, buffered=True)

    # 1. Fetch Attempt & Exam details
    cursor.execute("""
        SELECT ea.*, e.title, e.pass_percentage, c.course_name 
        FROM exam_attempts ea
        JOIN exams e ON ea.exam_id = e.exam_id
        JOIN courses c ON e.course_id = c.course_id
        WHERE ea.attempt_id = %s AND ea.student_id = %s
    """, (attempt_id, student_id))
    attempt = cursor.fetchone()

    if not attempt or attempt['status'] != 'finished':
        flash("Review not available.", "warning")
        return redirect(url_for('student.student_results'))

    # 2. Fetch the specific subset of questions served for this attempt
    cursor.execute("""
        SELECT q.*, sa.submitted_answer, sa.is_correct
        FROM questions q
        JOIN attempt_questions aq ON q.question_id = aq.question_id
        LEFT JOIN student_answers sa ON q.question_id = sa.question_id AND sa.attempt_id = %s
        WHERE aq.attempt_id = %s
    """, (attempt_id, attempt_id))
    review_questions = cursor.fetchall()

    for q in review_questions:
        # Fetch options for every question
        cursor.execute("SELECT * FROM options WHERE question_id = %s", (q['question_id'],))
        q['options'] = cursor.fetchall()

    cursor.close()
    connection.close()
    return render_template('student_review.html', attempt=attempt, questions=review_questions)

#! 3. VIOLATION LOGGING
@student.route('/log_violation', methods=['POST'])
def log_violation():
    data = request.get_json()
    attempt_id = data.get('attempt_id')
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    cursor.execute("UPDATE exam_attempts SET tab_switches = tab_switches + 1 WHERE attempt_id = %s", (attempt_id,))
    connection.commit()
    
    cursor.execute("SELECT tab_switches FROM exam_attempts WHERE attempt_id = %s", (attempt_id,))
    result = cursor.fetchone()
    new_count = result['tab_switches'] if result else 0
    
    cursor.close()
    connection.close()
    
    return jsonify({"status": "logged", "new_count": new_count})

#! 4. FINAL SUBMISSION
@student.route('/submit_exam/<int:attempt_id>', methods=['POST'])
def submit_exam(attempt_id):
    if not user_logged_in(): 
        return redirect(url_for('auth.login'))
    
    # Remove exam lockdown
    session.pop('active_exam_id', None)
    
    connection = mysql.connector.connect(**db_config)
    # FIX: Added buffered=True to allow multiple queries within the loop
    cursor = connection.cursor(dictionary=True, buffered=True)
    
    try:
        # 1. Get the exam ID associated with this attempt
        cursor.execute("SELECT exam_id FROM exam_attempts WHERE attempt_id = %s", (attempt_id,))
        attempt_info = cursor.fetchone()
        if not attempt_info:
            return redirect(url_for('student.student_dashboard'))
            
        exam_id = attempt_info['exam_id']
        
        # 2. Get all questions that belong to this exam
        cursor.execute("SELECT question_id FROM exam_questions WHERE exam_id = %s", (exam_id,))
        questions = cursor.fetchall()

        total_score = 0
        
        # 3. Loop through each question to check student's answer
        for q in questions:
            q_id = q['question_id']
            
            # Fetch the student's saved answer from the DB
            cursor.execute("""
                SELECT submitted_answer FROM student_answers 
                WHERE attempt_id = %s AND question_id = %s
            """, (attempt_id, q_id))
            student_row = cursor.fetchone()
            student_ans = str(student_row['submitted_answer']).strip().lower() if student_row else ""

            # Fetch the actual correct answer from the options table
            cursor.execute("""
                SELECT option_text FROM options 
                WHERE question_id = %s AND is_correct = 1
            """, (q_id,))
            correct_row = cursor.fetchone()
            correct_ans = str(correct_row['option_text']).strip().lower() if correct_row else None

            # 4. Compare and Grade
            if correct_ans and student_ans == correct_ans:
                # Mark as correct in individual answer row
                cursor.execute("""
                    UPDATE student_answers SET is_correct = 1 
                    WHERE attempt_id = %s AND question_id = %s
                """, (attempt_id, q_id))
                total_score += 1
            else:
                # Explicitly mark as wrong
                cursor.execute("""
                    UPDATE student_answers SET is_correct = 0 
                    WHERE attempt_id = %s AND question_id = %s
                """, (attempt_id, q_id))

        # 5. Finalize the main attempt record
        cursor.execute("""
            UPDATE exam_attempts 
            SET status = 'finished', end_time = NOW(), score = %s 
            WHERE attempt_id = %s
        """, (total_score, attempt_id))
        
        connection.commit()
        flash(f"Exam submitted successfully! Final Score: {total_score}", "success")
        
    except mysql.connector.Error as err:
        if connection:
            connection.rollback()
        flash(f"Grading Error: {err}", "danger")
        print(f"ERROR: {err}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
    
    return redirect(url_for('student.student_results'))


@student.route('/student_results')
def student_results():
    if not user_logged_in(): 
        return redirect(url_for('auth.login'))
    
    student_id = session.get('user_id')
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    try:

        cursor.execute("""
            SELECT 
                ea.*, 
                e.title, 
                e.pass_percentage, 
                c.course_name, 
                c.course_code,
                (SELECT COUNT(*) FROM attempt_questions WHERE attempt_id = ea.attempt_id) as total_served
            FROM exam_attempts ea
            JOIN exams e ON ea.exam_id = e.exam_id
            JOIN courses c ON e.course_id = c.course_id
            WHERE ea.student_id = %s 
              AND ea.status = 'finished' 
              AND e.archived = 0
            ORDER BY ea.end_time DESC
        """, (student_id,))
        results = cursor.fetchall()
        
    except mysql.connector.Error as err:
        flash(f"Error fetching results: {err}", "danger")
        results = []
    finally:
        cursor.close()
        connection.close()
        
    return render_template('student_results.html', results=results)

#! 5. COURSE CONTENT
@student.route('/course/<int:course_id>')
def view_course(course_id):
    if not user_logged_in():
        return redirect(url_for('auth.login'))
    
    student_id = session.get('user_id')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    try:
        # 1. Fetch Course & Teacher Details
        cursor.execute("""
            SELECT c.*, t.firstname as t_fname, t.lastname as t_lname, t.email as t_email 
            FROM courses c
            LEFT JOIN teachers t ON c.teacher_id = t.teacher_id
            WHERE c.course_id = %s
        """, (course_id,))
        course = cursor.fetchone()

        # 2. Fetch Student Progress stats for the header
        cursor.execute("SELECT COUNT(*) as total FROM exams WHERE course_id = %s AND is_active = 1 AND archived = 0", (course_id,))
        total_exams = cursor.fetchone()['total']

        cursor.execute("""
            SELECT COUNT(*) as completed FROM exam_attempts ea
            JOIN exams e ON ea.exam_id = e.exam_id
            WHERE e.course_id = %s AND ea.student_id = %s AND ea.status = 'finished' AND e.archived = 0;
        """, (course_id, student_id))
        completed_exams = cursor.fetchone()['completed']

        progress_pct = int((completed_exams / total_exams) * 100) if total_exams > 0 else 0

        cursor.execute("""
            SELECT 
                e.*, 
                ea.attempt_id,
                ea.status as attempt_status, 
                ea.score, 
                COALESCE(
                    (SELECT COUNT(*) FROM attempt_questions WHERE attempt_id = ea.attempt_id),
                    e.question_limit
                ) as total_q
            FROM exams e
            LEFT JOIN exam_attempts ea ON e.exam_id = ea.exam_id AND ea.student_id = %s
            WHERE e.course_id = %s AND e.archived = 0
        """, (student_id, course_id))
        course_exams = cursor.fetchall()
        
        now = datetime.now()
        for exam in course_exams:
            # Calculate the exact second the exam window closes
            exam['end_time'] = exam['date_time'] + timedelta(minutes=exam['duration_minutes'])
            
            # Logic: Can start if (Active) AND (Started) AND (Not Finished) AND (Not Expired)
            exam['is_expired'] = now > exam['end_time']
            exam['is_upcoming'] = now < exam['date_time']
            exam['can_take'] = (exam['is_active'] == 1 and not exam['is_upcoming'] and not exam['is_expired'] and exam['attempt_status'] != 'finished')

        return render_template('student_courses.html', 
                               course=course, 
                               course_exams=course_exams,
                               progress_pct=progress_pct,
                               now=now) # Ensure 'now' is passed
    finally:
        cursor.close()
        connection.close()