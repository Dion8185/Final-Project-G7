from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, make_response
import mysql.connector
from testpoint import db_config
from testpoint.Auth.login import user_logged_in
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import random
from fpdf import FPDF

student = Blueprint('student', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/student/static')

@student.before_app_request
def enforce_lockdown():
    # 1. Existing Exam Lockdown Logic
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

    # 2. Post-Approval Account Setup Guard
    if session.get('role') == 'student' and 'user_id' in session:
        # Exclude setup page and logout from redirect loop
        if request.endpoint in ['student.setup_account', 'auth.logout', 'static']:
            return
            
        student_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT block_id FROM students WHERE student_id = %s", (student_id,))
        res = cursor.fetchone()
        cursor.close(); connection.close()
        
        if res and res['block_id'] is None:
            return redirect(url_for('student.setup_account'))

@student.route('/setup-account', methods=['GET', 'POST'])
def setup_account():
    if not user_logged_in(): return redirect(url_for('auth.login'))
    
    student_id = session.get('user_id')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)

    if request.method == 'POST':
        block_id = request.form.get('block_id')
        
        # Security: Final Capacity Check
        cursor.execute("""
            SELECT b.capacity, (SELECT COUNT(*) FROM students WHERE block_id = b.block_id) as current_count
            FROM blocks b WHERE b.block_id = %s
        """, (block_id,))
        stats = cursor.fetchone()
        
        if stats and stats['current_count'] >= stats['capacity']:
            flash("Sorry, this block just reached its capacity. Please select another block.", "warning")
            return redirect(url_for('student.setup_account'))

        # Update Student Record
        cursor.execute("UPDATE students SET block_id = %s WHERE student_id = %s", (block_id, student_id))
        connection.commit()
        cursor.close(); connection.close()
        
        flash("Your account setup is complete! You can now access your dashboard.", "success")
        return redirect(url_for('student.student_dashboard'))

    # GET: Fetch Data for UI
    cursor.execute("SELECT * FROM programs WHERE is_active = 1")
    programs = cursor.fetchall()
    
    cursor.execute("""
        SELECT b.*, p.program_name,
        (b.capacity - (SELECT COUNT(*) FROM students WHERE block_id = b.block_id)) as slots_left
        FROM blocks b
        JOIN programs p ON b.program_id = p.program_id
        WHERE b.is_active = 1
        HAVING slots_left > 0
    """)
    blocks = cursor.fetchall()
    
    cursor.close(); connection.close()
    return render_template('student_setup.html', programs=programs, blocks=blocks)

@student.app_context_processor
def inject_enrolled_courses():
    if 'user_id' in session and session.get('role') == 'student':
        student_id = session.get('user_id')
        try:
            connection = mysql.connector.connect(**db_config)
            cursor = connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT cl.class_code as course_id, cl.class_code, c.course_name, c.course_code 
                FROM classes cl
                JOIN courses c ON cl.course_code = c.course_code
                JOIN enrollments e ON cl.class_code = e.class_code
                WHERE e.student_id = %s
            """, (student_id,))
            courses = cursor.fetchall()
            cursor.close()
            connection.close()
            return dict(enrolled_courses=courses)
        except Exception as e:
            return dict(enrolled_courses=[])
    return dict(enrolled_courses=[])


#! 1. DASHBOARD
@student.route('/student_dashboard')
def student_dashboard():
    if not user_logged_in():
        flash('Please log in to access the dashboard.', 'danger')
        return redirect(url_for('auth.login'))

    student_id = session.get('user_id')
    student_firstname = session.get('firstname')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("SELECT COUNT(*) as count FROM enrollments WHERE student_id = %s AND status = 'active'", (student_id,))
        course_count = cursor.fetchone()['count']

        cursor.execute("""
            SELECT COUNT(*) as count FROM exam_attempts ea 
            JOIN exams e ON ea.exam_id = e.exam_id 
            WHERE ea.student_id = %s AND ea.status = 'finished' AND e.archived = 0
        """, (student_id,))
        completed_count = cursor.fetchone()['count']
        
        cursor.execute("""
            SELECT COUNT(*) as count FROM exams e
            JOIN enrollments en ON e.class_code = en.class_code
            LEFT JOIN exam_attempts ea ON e.exam_id = ea.exam_id AND ea.student_id = %s
            WHERE en.student_id = %s AND en.status = 'active' AND e.is_active = 1 
            AND (ea.status IS NULL OR ea.status = 'in-progress') AND e.archived = 0;
        """, (student_id, student_id))
        available_count = cursor.fetchone()['count']

        # Protection against division by zero using NULLIF
        cursor.execute("""
            SELECT AVG(percentage) as overall_avg FROM (
                SELECT (ea.score / NULLIF((SELECT COUNT(*) FROM attempt_questions WHERE attempt_id = ea.attempt_id), 0) * 100) as percentage
                FROM exam_attempts ea
                JOIN exams e ON ea.exam_id = e.exam_id
                WHERE ea.student_id = %s AND ea.status = 'finished' AND e.archived = 0
            ) as sub
        """, (student_id,))
        avg_res = cursor.fetchone()
        overall_avg = round(float(avg_res['overall_avg']), 1) if avg_res and avg_res['overall_avg'] else 0

        cursor.execute("""
            SELECT e.title, e.date_time, c.course_name, e.duration_minutes
            FROM exams e
            JOIN enrollments en ON e.class_code = en.class_code
            JOIN classes cl ON e.class_code = cl.class_code
            JOIN courses c ON cl.course_code = c.course_code
            LEFT JOIN exam_attempts ea ON e.exam_id = ea.exam_id AND ea.student_id = %s
            WHERE en.student_id = %s AND e.is_active = 1 
            AND (ea.status IS NULL OR ea.status = 'in-progress') AND e.archived = 0
            ORDER BY e.date_time ASC LIMIT 3
        """, (student_id, student_id))
        upcoming_exams = cursor.fetchall()

        cursor.execute("""
            SELECT e.title, ea.score, ea.end_time,
                   (SELECT COUNT(*) FROM attempt_questions WHERE attempt_id = ea.attempt_id) as total
            FROM exam_attempts ea
            JOIN exams e ON ea.exam_id = e.exam_id
            WHERE ea.student_id = %s AND ea.status = 'finished' AND e.archived = 0
            ORDER BY ea.end_time DESC LIMIT 3
        """, (student_id,))
        recent_results = cursor.fetchall()

        cursor.execute("""
            SELECT e.title, 
                   COALESCE((ea.score / NULLIF((SELECT COUNT(*) FROM attempt_questions WHERE attempt_id = ea.attempt_id), 0) * 100), 0) as percentage
                FROM exam_attempts ea
                JOIN exams e ON ea.exam_id = e.exam_id
                WHERE ea.student_id = %s AND ea.status = 'finished' AND e.archived = 0
                ORDER BY ea.end_time ASC LIMIT 7
        """, (student_id,))
        performance_trend = cursor.fetchall()
        trend_labels = [p['title'] for p in performance_trend]
        trend_scores = [round(float(p['percentage']), 1) for p in performance_trend]

        cursor.execute("""
            SELECT rank_data.class_code, c.course_name, rank_data.student_avg, rank_data.class_rank, rank_data.total_students
            FROM (
                SELECT t.class_code, t.student_id, t.student_avg,
                    RANK() OVER (PARTITION BY t.class_code ORDER BY t.student_avg DESC) as class_rank,
                    COUNT(*) OVER (PARTITION BY t.class_code) as total_students
                FROM (
                    SELECT en.class_code, en.student_id, 
                        AVG(COALESCE(ea.score / NULLIF((SELECT COUNT(*) FROM attempt_questions WHERE attempt_id = ea.attempt_id), 0) * 100, 0)) as student_avg
                    FROM enrollments en
                    LEFT JOIN exams e ON en.class_code = e.class_code
                    LEFT JOIN exam_attempts ea ON e.exam_id = ea.exam_id AND en.student_id = ea.student_id
                    WHERE (ea.status = 'finished' OR ea.status IS NULL)
                    GROUP BY en.class_code, en.student_id
                ) t
            ) rank_data
            JOIN classes cl ON rank_data.class_code = cl.class_code
            JOIN courses c ON cl.course_code = c.course_code
            WHERE rank_data.student_id = %s
        """, (student_id,))
        rankings = cursor.fetchall()

        return render_template('student_dashboard.html', 
                               course_count=course_count, 
                               completed_count=completed_count, 
                               available_count=available_count,
                               overall_avg=overall_avg,
                               student_firstname=student_firstname,
                               upcoming_exams=upcoming_exams,
                               recent_results=recent_results,
                               trend_labels=trend_labels,
                               trend_scores=trend_scores,
                               rankings=rankings)
    finally:
        cursor.close(); connection.close()

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
            # ... (keep your existing POST logic for updates)
            firstname = request.form.get('firstname')
            middlename = request.form.get('middlename')
            lastname = request.form.get('lastname')
            new_password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')

            cursor.execute("""
                UPDATE students SET firstname = %s, middlename = %s, lastname = %s 
                WHERE student_id = %s
            """, (firstname, middlename, lastname, user_id))

            if new_password:
                if new_password == confirm_password:
                    cursor.execute("UPDATE users SET password = %s WHERE user_id = %s", 
                                   (generate_password_hash(new_password), user_id))
                else:
                    flash('Passwords do not match.', 'warning')
                    return redirect(url_for('student.profile'))

            connection.commit()
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('student.profile'))

        # --- GET: FETCH DETAILED STUDENT DATA ---
        cursor.execute("""
            SELECT u.user_id, u.email, u.role, u.created_at,
                   s.firstname, s.middlename, s.lastname,
                   s.region, s.province, s.city, s.barangay,
                   b.block_name, pr.program_name, pr.description as program_desc
            FROM users u
            JOIN students s ON u.user_id = s.student_id
            LEFT JOIN blocks b ON s.block_id = b.block_id
            LEFT JOIN programs pr ON b.program_id = pr.program_id
            WHERE u.user_id = %s
        """, (user_id,))
        user_data = cursor.fetchone()

        # Fetch Academic Stats for the profile view
        cursor.execute("SELECT COUNT(*) as count FROM enrollments WHERE student_id = %s AND status = 'active'", (user_id,))
        course_count = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM exam_attempts WHERE student_id = %s AND status = 'finished'", (user_id,))
        exam_count = cursor.fetchone()['count']

        return render_template('student_profile.html', 
                               user=user_data, 
                               course_count=course_count, 
                               exam_count=exam_count)

    finally:
        cursor.close(); connection.close()

#! 2. AVAILABLE EXAMS
@student.route('/student_exams')
def student_exams():
    if user_logged_in():
        student_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        # We no longer check enrollment status for blocking, we check ea.status
        cursor.execute("""
            SELECT e.*, c.course_name, c.course_code, ea.status as attempt_status, cl.class_code as course_id
            FROM exams e
            JOIN classes cl ON e.class_code = cl.class_code
            JOIN courses c ON cl.course_code = c.course_code
            JOIN enrollments en ON e.class_code = en.class_code
            LEFT JOIN exam_attempts ea ON e.exam_id = ea.exam_id AND ea.student_id = %s
            WHERE en.student_id = %s AND e.archived = 0;
        """, (student_id, student_id))
        exams = cursor.fetchall()
        
        now = datetime.now()
        for exam in exams:
            start_time = exam['date_time']
            end_time = start_time + timedelta(minutes=exam['duration_minutes']) if start_time else None
            
            exam['status_label'] = "Available"
            exam['status_class'] = "primary"
            exam['can_start'] = False

            # SPECIFIC BLOCK CHECK
            if exam['attempt_status'] == 'blocked':
                exam['status_label'] = "Blocked"
                exam['status_class'] = "dark"
            elif exam['attempt_status'] == 'finished':
                exam['status_label'] = "Completed"
                exam['status_class'] = "success"
            elif exam['is_active'] == 0:
                exam['status_label'] = "Unavailable"
                exam['status_class'] = "secondary"
            elif not start_time:
                exam['status_label'] = "TBA"
                exam['status_class'] = "secondary"
            elif now < start_time:
                exam['status_label'] = "Upcoming"
                exam['status_class'] = "warning"
            elif now > end_time:
                exam['status_label'] = "Missed / Expired"
                exam['status_class'] = "danger"
            else:
                exam['status_label'] = "Ongoing"
                exam['status_class'] = "success"
                exam['can_start'] = True

        cursor.close(); connection.close()
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
    cursor = connection.cursor(dictionary=True)
    try:
        # REAL-TIME SECURITY CHECK: Verify student isn't blocked mid-exam
        cursor.execute("SELECT status FROM exam_attempts WHERE attempt_id = %s", (attempt_id,))
        attempt = cursor.fetchone()
        
        if not attempt or attempt['status'] == 'blocked':
            return jsonify({"status": "blocked", "message": "Access restricted by instructor."}), 403

        # Proceed with saving if not blocked
        cursor.execute("""
            INSERT INTO student_answers (attempt_id, question_id, submitted_answer, is_flagged)
            VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE submitted_answer = %s, is_flagged = %s
        """, (attempt_id, q_id, ans, is_flagged, ans, is_flagged))
        
        cursor.execute("UPDATE exam_attempts SET current_q_index = %s WHERE attempt_id = %s", (current_idx, attempt_id))
        connection.commit()
        return jsonify({"status": "saved"})
    finally:
        cursor.close()
        connection.close()

#! 2. TAKE EXAM (PERSISTENT & RANDOMIZED LOGIC)
@student.route('/take_exam/<int:exam_id>')
def take_exam(exam_id):
    if not user_logged_in(): 
        return redirect(url_for('auth.login'))
        
    student_id = session.get('user_id')
    
    connection = mysql.connector.connect(**db_config)
    # Using buffered=True to handle multiple queries without "Unread Result" errors
    cursor = connection.cursor(dictionary=True, buffered=True)

    try:
        # 1. SECURITY: ENROLLMENT & BLOCKING CHECK
        cursor.execute("""
            SELECT status FROM exam_attempts 
            WHERE exam_id = %s AND student_id = %s
        """, (exam_id, student_id))
        existing_status = cursor.fetchone()
        
        if existing_status and existing_status['status'] == 'blocked':
            flash("You are currently blocked from taking this exam.", "danger")
            return redirect(url_for('student.student_exams'))

        # 2. EXAM METADATA & TIMER LOGIC
        cursor.execute("""
            SELECT *, TIMESTAMPDIFF(SECOND, NOW(), DATE_ADD(date_time, INTERVAL duration_minutes MINUTE)) as rem 
            FROM exams WHERE exam_id = %s
        """, (exam_id,))
        exam = cursor.fetchone()
        
        if not exam or exam['is_active'] == 0:
            flash("This exam is currently unavailable.", "warning")
            return redirect(url_for('student.student_exams'))

        if exam['rem'] <= 0:
            session.pop('active_exam_id', None) 
            flash("This exam session has already expired.", "danger")
            return redirect(url_for('student.student_exams'))

        # 3. ATTEMPT PERSISTENCE CHECK
        cursor.execute("SELECT * FROM exam_attempts WHERE student_id = %s AND exam_id = %s", (student_id, exam_id))
        attempt = cursor.fetchone()

        if not attempt:
            # --- START NEW ATTEMPT ---
            cursor.execute("""
                INSERT INTO exam_attempts (student_id, exam_id, status, start_time) 
                VALUES (%s, %s, 'in-progress', NOW())
            """, (student_id, exam_id))
            connection.commit()
            attempt_id = cursor.lastrowid
            
            # THE SUBSET RANDOMIZATION: Pick random IDs from the pool
            limit = exam.get('question_limit') or 50
            cursor.execute("""
                INSERT INTO attempt_questions (attempt_id, question_id)
                SELECT %s, question_id FROM exam_questions 
                WHERE exam_id = %s 
                ORDER BY RAND() 
                LIMIT %s
            """, (attempt_id, exam_id, limit))
            connection.commit()
            
            current_q = 0
            tab_switches = 0
        else:
            # --- RESUME EXISTING ATTEMPT ---
            if attempt['status'] == 'finished':
                session.pop('active_exam_id', None)
                flash("You have already completed this exam.", "info")
                return redirect(url_for('student.student_results'))
            
            attempt_id = attempt['attempt_id']
            current_q = attempt['current_q_index']
            tab_switches = attempt['tab_switches']

        # 4. LOCKDOWN ENFORCEMENT
        session['active_exam_id'] = exam_id

        # 5. FETCH AND SHUFFLE QUESTIONS (The Fix for Student-Specific Randomization)
        cursor.execute("""
            SELECT q.* FROM questions q
            JOIN attempt_questions aq ON q.question_id = aq.question_id
            WHERE aq.attempt_id = %s
        """, (attempt_id,))
        questions = cursor.fetchall()
        
        rng = random.Random(attempt_id)
        rng.shuffle(questions)

        # 6. ATTACH OPTIONS & SAVED ANSWERS
        for q in questions:
            cursor.execute("SELECT * FROM options WHERE question_id = %s", (q['question_id'],))
            q['options'] = cursor.fetchall()
            
            cursor.execute("""
                SELECT submitted_answer, is_flagged FROM student_answers 
                WHERE attempt_id = %s AND question_id = %s
            """, (attempt_id, q['question_id']))
            ans_row = cursor.fetchone()
            
            q['saved_answer'] = ans_row['submitted_answer'] if ans_row else ""
            q['is_flagged'] = ans_row['is_flagged'] if ans_row else 0

        return render_template('take_exam.html', 
                               exam=exam, 
                               questions=questions, 
                               attempt_id=attempt_id, 
                               remaining_seconds=exam['rem'], 
                               current_q=current_q, 
                               tab_switches=tab_switches)

    except mysql.connector.Error as err:
        if connection:
            connection.rollback()
        flash(f"Database Error: {err}", "danger")
        return redirect(url_for('student.student_exams'))
        
    finally:
        cursor.close()
        connection.close()
        
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
        JOIN classes cl ON e.class_code = cl.class_code
        JOIN courses c ON cl.course_code = c.course_code
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

@student.route('/log_violation', methods=['POST'])
def log_violation():
    data = request.get_json()
    attempt_id = data.get('attempt_id')
    violation_type = data.get('violation_type', 'Tab Switch/Blur')
    lat = data.get('lat')
    lng = data.get('lng')
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    try:
        # REAL-TIME SECURITY CHECK
        cursor.execute("SELECT status FROM exam_attempts WHERE attempt_id = %s", (attempt_id,))
        attempt = cursor.fetchone()
        
        if not attempt or attempt['status'] == 'blocked':
            return jsonify({"status": "blocked"}), 403

        # 1. Define which events actually count as "Violations" to increment the counter
        # Events like 'Exam Started' and 'Exam Ended' will NOT increment this count.
        violations_to_count = ['Window switch/blur', 'Fullscreen exited', 'Tab Switch']
        
        if violation_type in violations_to_count:
            cursor.execute("UPDATE exam_attempts SET tab_switches = tab_switches + 1 WHERE attempt_id = %s", (attempt_id,))
        
        # 2. ALWAYS log the entry to the detailed violation_logs table for the teacher's timeline
        cursor.execute("""
            INSERT INTO violation_logs (attempt_id, violation_type, violation_time, latitude, longitude) 
            VALUES (%s, %s, NOW(), %s, %s)
        """, (attempt_id, violation_type, lat, lng))
        
        connection.commit()
        
        # Fetch new count to return to UI
        cursor.execute("SELECT tab_switches FROM exam_attempts WHERE attempt_id = %s", (attempt_id,))
        result = cursor.fetchone()
        new_count = result['tab_switches'] if result else 0
        
        return jsonify({"status": "logged", "new_count": new_count})
    finally:
        cursor.close()
        connection.close()
        
#! 4. FINAL SUBMISSION
@student.route('/submit_exam/<int:attempt_id>', methods=['POST'])
def submit_exam(attempt_id):
    if not user_logged_in(): 
        return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True, buffered=True)
    
    try:
        # REAL-TIME SECURITY CHECK: Reject submission if blocked
        cursor.execute("SELECT status, exam_id FROM exam_attempts WHERE attempt_id = %s", (attempt_id,))
        attempt_info = cursor.fetchone()
        
        if not attempt_info or attempt_info['status'] == 'blocked':
            session.pop('active_exam_id', None)
            flash("Submission failed: Your access to this exam was restricted by the instructor.", "danger")
            return redirect(url_for('student.student_exams'))

        # Remove exam lockdown
        session.pop('active_exam_id', None)
        
        # Grading Logic (Existing)
        cursor.execute("SELECT question_id FROM attempt_questions WHERE attempt_id = %s", (attempt_id,))
        questions = cursor.fetchall()
        total_score = 0
        
        for q in questions:
            q_id = q['question_id']
            cursor.execute("SELECT submitted_answer FROM student_answers WHERE attempt_id = %s AND question_id = %s", (attempt_id, q_id))
            student_row = cursor.fetchone()
            student_ans = str(student_row['submitted_answer']).strip().lower() if student_row else ""

            cursor.execute("SELECT option_text FROM options WHERE question_id = %s AND is_correct = 1", (q_id,))
            correct_row = cursor.fetchone()
            correct_ans = str(correct_row['option_text']).strip().lower() if correct_row else None

            if correct_ans and student_ans == correct_ans:
                cursor.execute("UPDATE student_answers SET is_correct = 1 WHERE attempt_id = %s AND question_id = %s", (attempt_id, q_id))
                total_score += 1
            else:
                cursor.execute("UPDATE student_answers SET is_correct = 0 WHERE attempt_id = %s AND question_id = %s", (attempt_id, q_id))

        cursor.execute("""
            UPDATE exam_attempts 
            SET status = 'finished', end_time = NOW(), score = %s 
            WHERE attempt_id = %s
        """, (total_score, attempt_id))
        
        connection.commit()
        flash(f"Exam submitted successfully! Final Score: {total_score}", "success")
        
    except mysql.connector.Error as err:
        if connection: connection.rollback()
        flash(f"Grading Error: {err}", "danger")
    finally:
        cursor.close(); connection.close()
    
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
            JOIN classes cl ON e.class_code = cl.class_code
            JOIN courses c ON cl.course_code = c.course_code
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

@student.route('/course/<string:course_id>')
def view_course(course_id):
    if not user_logged_in():
        return redirect(url_for('auth.login'))
    
    student_id = session.get('user_id')
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    try:
        # Fetch Course & Teacher Details
        cursor.execute("""
            SELECT c.*, cl.class_code, t.firstname as t_fname, t.lastname as t_lname, t.email as t_email 
            FROM classes cl
            JOIN courses c ON cl.course_code = c.course_code
            LEFT JOIN teachers t ON cl.teacher_id = t.teacher_id
            WHERE cl.class_code = %s
        """, (course_id,))
        course = cursor.fetchone()
    
        # Fetch Exam List with per-exam attempt status
        cursor.execute("""
            SELECT 
                e.*, 
                ea.attempt_id,
                ea.status as attempt_status, 
                ea.score, 
                (SELECT COUNT(*) FROM exam_questions WHERE exam_id = e.exam_id) as total_q
            FROM exams e
            LEFT JOIN exam_attempts ea ON e.exam_id = ea.exam_id AND ea.student_id = %s
            WHERE e.class_code = %s AND e.archived = 0
        """, (student_id, course_id))
        course_exams = cursor.fetchall()

        # Stats for header
        total_exams = len(course_exams)
        completed_exams = sum(1 for ex in course_exams if ex['attempt_status'] == 'finished')
        progress_pct = int((completed_exams / total_exams) * 100) if total_exams > 0 else 0
        
        now = datetime.now()
        for exam in course_exams:
            if exam['date_time']:
                exam['end_time'] = exam['date_time'] + timedelta(minutes=exam['duration_minutes'])
                exam['is_expired'] = now > exam['end_time']
                exam['is_upcoming'] = now < exam['date_time']
            else:
                exam['is_expired'] = False
                exam['is_upcoming'] = True

            # can_take is true if active, not upcoming, not expired, and NOT finished or blocked
            exam['can_take'] = (exam['is_active'] == 1 and not exam['is_upcoming'] and 
                               not exam['is_expired'] and exam['attempt_status'] not in ['finished', 'blocked'])

        return render_template('student_courses.html', 
                               course=course, 
                               course_exams=course_exams,
                               progress_pct=progress_pct,
                               total_exams=total_exams,
                               completed_exams=completed_exams,
                               now=now)
    finally:
        cursor.close()
        connection.close()

#! 5. ANALYTICS & INSIGHTS
@student.route('/student_analytics')
def student_analytics():
    if not user_logged_in():
        return redirect(url_for('auth.login'))

    student_id = session.get('user_id')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)

    try:
        # 1. COMPREHENSIVE STANDINGS (Leaderboard Logic)
        cursor.execute("""
            SELECT 
                r.class_code,
                c.course_name,
                r.student_id,
                s.firstname, s.lastname,
                r.avg_score,
                RANK() OVER (PARTITION BY r.class_code ORDER BY r.avg_score DESC) as rank_pos,
                COUNT(*) OVER (PARTITION BY r.class_code) as total_peers
            FROM (
                SELECT 
                    en.class_code, 
                    en.student_id, 
                    AVG(
                        COALESCE(
                            (ea.score / NULLIF(
                                (SELECT COUNT(*) 
                                FROM attempt_questions aq 
                                WHERE aq.attempt_id = ea.attempt_id
                                ), 0)
                            ) * 100, 
                        0)
                    ) as avg_score
                FROM enrollments en
                LEFT JOIN exam_attempts ea 
                    ON en.student_id = ea.student_id
                LEFT JOIN exams e 
                    ON ea.exam_id = e.exam_id
                WHERE 
                    (ea.status = 'finished' OR ea.status IS NULL)
                    AND (e.archived = 0 OR e.archived IS NULL)
                GROUP BY en.class_code, en.student_id
            ) r
            JOIN students s 
                ON r.student_id = s.student_id
            JOIN classes cl 
                ON r.class_code = cl.class_code
            JOIN courses c 
                ON cl.course_code = c.course_code
            WHERE r.class_code IN (
                SELECT class_code 
                FROM enrollments 
                WHERE student_id = %s
            )
            ORDER BY r.class_code, rank_pos ASC
        """, (student_id,))

        raw_standings = cursor.fetchall()
        
        # Group standings by course for the UI
        standings_by_course = {}
        for row in raw_standings:
            course = row['course_name']
            if course not in standings_by_course:
                standings_by_course[course] = []
            standings_by_course[course].append(row)

        # 2. ITEM ANALYSIS (The "Class Killers")
        # Identify questions in the student's courses that have the highest failure rate globally
        cursor.execute("""
            SELECT 
                q.question_text, 
                c.course_name,
                COUNT(sa.answer_id) as total_attempts,
                SUM(CASE WHEN sa.is_correct = 0 THEN 1 ELSE 0 END) as fail_count,
                (SUM(CASE WHEN sa.is_correct = 0 THEN 1 ELSE 0 END) / COUNT(sa.answer_id) * 100) as difficulty_index
            FROM student_answers sa
            JOIN questions q ON sa.question_id = q.question_id
            JOIN courses c ON q.course_code = c.course_code
            JOIN enrollments en ON en.student_id = %s
            JOIN classes cl ON en.class_code = cl.class_code AND cl.course_code = c.course_code
            GROUP BY q.question_id, q.question_text, c.course_name
            HAVING total_attempts > 2
            ORDER BY difficulty_index DESC
            LIMIT 5
        """, (student_id,))
        item_analysis = cursor.fetchall()

        # 3. EXAM STATISTICS (Pass/Fail Distribution)
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN (ea.score / (SELECT COUNT(*) FROM attempt_questions WHERE attempt_id = ea.attempt_id) * 100) >= e.pass_percentage THEN 1 ELSE 0 END) as pass_count,
                SUM(CASE WHEN (ea.score / (SELECT COUNT(*) FROM attempt_questions WHERE attempt_id = ea.attempt_id) * 100) < e.pass_percentage THEN 1 ELSE 0 END) as fail_count
            FROM exam_attempts ea
            JOIN exams e ON ea.exam_id = e.exam_id
            WHERE ea.student_id = %s AND ea.status = 'finished' AND e.archived = 0
        """, (student_id,))
        stats = cursor.fetchone()

        return render_template('student_analytics.html', 
                               standings=standings_by_course,
                               item_analysis=item_analysis,
                               stats=stats,
                               student_id=student_id)
    finally:
        cursor.close()
        connection.close()

#! 6. CERTIFICATES & TRANSCRIPTS
@student.route('/student_certificates')
def student_certificates():
    if not user_logged_in():
        flash('Please log in to view your credentials.', 'danger')
        return redirect(url_for('auth.login'))

    student_id = session.get('user_id')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)

    try:
        # EXAM ACHIEVEMENTS (Top 1-3) - Protected against 0 questions
        cursor.execute("""
            SELECT * FROM (
                SELECT 
                    ea.attempt_id, e.title as assessment_name, c.course_name, c.course_code,
                    ea.score, (SELECT COUNT(*) FROM attempt_questions WHERE attempt_id = ea.attempt_id) as total_q,
                    ea.end_time as issued_date,
                    RANK() OVER (PARTITION BY ea.exam_id ORDER BY (ea.score / NULLIF((SELECT COUNT(*) FROM attempt_questions WHERE attempt_id = ea.attempt_id), 0)) DESC) as exam_rank
                FROM exam_attempts ea
                JOIN exams e ON ea.exam_id = e.exam_id
                JOIN classes cl ON e.class_code = cl.class_code
                JOIN courses c ON cl.course_code = c.course_code
                WHERE ea.status = 'finished' AND e.archived = 0
            ) AS ranked_exams
            WHERE ranked_exams.attempt_id IN (SELECT attempt_id FROM exam_attempts WHERE student_id = %s)
            AND exam_rank <= 3 AND total_q > 0
            ORDER BY course_name ASC, exam_rank ASC
        """, (student_id,))
        exam_certs = cursor.fetchall()
        # COURSE HONORS (Top 20) - Protected against 0 questions + excludes archived exams
        cursor.execute("""
            SELECT * FROM (
                SELECT 
                    en.student_id, 
                    c.course_name, 
                    c.course_code, 
                    cl.class_code,

                    AVG(
                        COALESCE(
                            (ea.score / NULLIF(
                                (SELECT COUNT(*) 
                                FROM attempt_questions aq 
                                WHERE aq.attempt_id = ea.attempt_id
                                ), 0)
                            ) * 100,
                        0)
                    ) as avg_pct,

                    RANK() OVER (
                        PARTITION BY cl.class_code 
                        ORDER BY AVG(
                            COALESCE(
                                (ea.score / NULLIF(
                                    (SELECT COUNT(*) 
                                    FROM attempt_questions aq 
                                    WHERE aq.attempt_id = ea.attempt_id
                                    ), 0)
                                ), 
                            0)
                        ) DESC
                    ) as course_rank

                FROM enrollments en
                JOIN classes cl 
                    ON en.class_code = cl.class_code
                JOIN courses c 
                    ON cl.course_code = c.course_code

                LEFT JOIN exams e 
                    ON cl.class_code = e.class_code

                LEFT JOIN exam_attempts ea 
                    ON e.exam_id = ea.exam_id 
                    AND en.student_id = ea.student_id

                WHERE 
                    (ea.status = 'finished' OR ea.status IS NULL)
                    AND (e.archived = 0 OR e.archived IS NULL)

                GROUP BY en.student_id, cl.class_code
            ) AS ranked_courses

            WHERE 
                ranked_courses.student_id = %s 
                AND course_rank <= 20 
                AND avg_pct IS NOT NULL

            ORDER BY avg_pct DESC
        """, (student_id,))

        course_certs = cursor.fetchall()

        cursor.execute("""
            SELECT e.title, c.course_name, c.course_code, ea.score, ea.end_time,
                   (SELECT COUNT(*) FROM attempt_questions WHERE attempt_id = ea.attempt_id) as total_q,
                   e.pass_percentage
            FROM exam_attempts ea
            JOIN exams e ON ea.exam_id = e.exam_id
            JOIN classes cl ON e.class_code = cl.class_code
            JOIN courses c ON cl.course_code = c.course_code
            WHERE ea.student_id = %s AND ea.status = 'finished' AND e.archived = 0
            ORDER BY ea.end_time DESC
        """, (student_id,))
        transcripts = cursor.fetchall()

        return render_template('student_certificates.html', 
                               exam_certs=exam_certs, 
                               course_certs=course_certs,
                               transcripts=transcripts,
                               student_id = student_id)

    finally:
        cursor.close(); connection.close()