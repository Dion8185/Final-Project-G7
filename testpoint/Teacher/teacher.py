from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file
from testpoint import db_config
from testpoint.Auth.login import teacher_logged_in
import mysql.connector
import pandas as pd 
import io
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
import google.generativeai as genai
import pdfplumber
import json
import os
from dotenv import load_dotenv

teacher = Blueprint('teacher', __name__, template_folder='templates', static_folder='static',
                    static_url_path='/teacher/static')

load_dotenv("testpoint/passwordDB.env")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
ai_model = genai.GenerativeModel('gemini-3-flash-preview')

@teacher.context_processor
def inject_teacher_courses():
    if session.get('role') == 'teacher':
        teacher_id = session.get('user_id')
        try:
            connection = mysql.connector.connect(**db_config)
            cursor = connection.cursor(dictionary=True)
            # Fetch courses assigned to this teacher
            cursor.execute("""
                SELECT cl.class_code, c.course_name
                FROM classes cl 
                JOIN courses c ON cl.course_code = c.course_code
                WHERE cl.teacher_id = %s AND cl.is_active = 1
            """, (teacher_id,))
            courses = cursor.fetchall()
            cursor.close()
            connection.close()
            return dict(assigned_courses=courses)
        except Exception:
            return dict(assigned_courses=[])
    return dict(assigned_courses=[])

#! 1. DASHBOARD & OVERVIEW
@teacher.route('/')
def teacher_dashboard():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        try:
            # 1. Dashboard Stats
            cursor.execute("SELECT COUNT(DISTINCT course_code) as count FROM classes WHERE teacher_id = %s", (teacher_id,))
            course_count = cursor.fetchone()['count']

            cursor.execute("""
                SELECT COUNT(*) as count FROM exam_attempts ea 
                JOIN exams ex ON ea.exam_id = ex.exam_id 
                JOIN classes cl ON ex.class_code = cl.class_code 
                WHERE cl.teacher_id = %s AND ea.status = 'in-progress'
            """, (teacher_id,))
            active_examinees = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM questions WHERE teacher_id = %s AND is_isolated = 0", (teacher_id,))
            total_q = cursor.fetchone()['count']

            cursor.execute("""
                SELECT SUM(ea.tab_switches) as total FROM exam_attempts ea 
                JOIN exams ex ON ea.exam_id = ex.exam_id 
                JOIN classes cl ON ex.class_code = cl.class_code 
                WHERE cl.teacher_id = %s
            """, (teacher_id,))
            total_violations = cursor.fetchone()['total'] or 0

            # 2. Exam Pipeline (Drafts vs published)
            cursor.execute("SELECT is_active, COUNT(*) as count FROM exams WHERE created_by = %s AND archived = 0 GROUP BY is_active", (teacher_id,))
            exam_stats = cursor.fetchall()
            draft_count = sum(item['count'] for item in exam_stats if item['is_active'] == 0)
            published_count = sum(item['count'] for item in exam_stats if item['is_active'] == 1)

            # 3. Course Performance (Chart Data)
            cursor.execute("""
                SELECT c.course_name, AVG((ea.score / ex.question_limit) * 100) as avg_score
                FROM exam_attempts ea
                JOIN exams ex ON ea.exam_id = ex.exam_id
                JOIN classes cl ON ex.class_code = cl.class_code
                JOIN courses c ON cl.course_code = c.course_code
                WHERE cl.teacher_id = %s AND ea.status = 'finished' AND ex.archived = 0
                GROUP BY c.course_code LIMIT 5
            """, (teacher_id,))
            course_data = cursor.fetchall()
            course_labels = [d['course_name'][:15] + '...' if len(d['course_name']) > 15 else d['course_name'] for d in course_data]
            course_avgs = [round(float(d['avg_score']), 1) for d in course_data]

            # 4. Upcoming Schedule
            cursor.execute("""
                SELECT ex.title, ex.date_time, c.course_name 
                FROM exams ex 
                JOIN classes cl ON ex.class_code = cl.class_code 
                JOIN courses c ON cl.course_code = c.course_code
                WHERE cl.teacher_id = %s AND ex.date_time > NOW() AND ex.archived = 0
                ORDER BY ex.date_time ASC LIMIT 3
            """, (teacher_id,))
            upcoming_exams = cursor.fetchall()

            # 5. Question Type Distribution (Pie)
            cursor.execute("SELECT question_type, COUNT(*) as count FROM questions WHERE teacher_id = %s AND is_isolated = 0 GROUP BY question_type", (teacher_id,))
            dist_data = cursor.fetchall()
            type_mapping = {'multiple_choice': 'MCQ', 'true_false': 'T/F', 'identification': 'Ident.', 'essay': 'Essay'}
            dist_labels = [type_mapping.get(d['question_type'], d['question_type']) for d in dist_data]
            dist_values = [int(d['count']) for d in dist_data]

            # 6. Recent Submissions
            cursor.execute("""
                SELECT ea.score, s.firstname, s.lastname, ex.title, ea.end_time, ex.question_limit
                FROM exam_attempts ea
                JOIN students s ON ea.student_id = s.student_id
                JOIN exams ex ON ea.exam_id = ex.exam_id
                JOIN classes cl ON ex.class_code = cl.class_code
                WHERE cl.teacher_id = %s AND ea.status = 'finished' AND ex.archived = 0
                ORDER BY ea.end_time DESC LIMIT 5
            """, (teacher_id,))
            recent_submissions = cursor.fetchall()

            return render_template('teacher_dashboard.html', 
                                   firstname=session.get('firstname'),
                                   course_count=course_count,
                                   active_examinees=active_examinees,
                                   total_q=total_q, 
                                   total_violations=total_violations, 
                                   draft_count=draft_count,
                                   published_count=published_count,
                                   course_labels=course_labels,
                                   course_avgs=course_avgs,
                                   upcoming_exams=upcoming_exams,
                                   dist_labels=dist_labels, 
                                   dist_values=dist_values, 
                                   recent_submissions=recent_submissions)
        finally: 
            cursor.close()
            connection.close()
            
    return redirect(url_for('auth.login'))

@teacher.route('/question_bank')
def question_bank():
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT DISTINCT c.*, (SELECT COUNT(*) FROM questions WHERE course_code = c.course_code AND teacher_id = %s AND is_isolated = 0) as question_count 
            FROM courses c 
            JOIN classes cl ON c.course_code = cl.course_code 
            WHERE cl.teacher_id = %s
        """, (session.get('user_id'), session.get('user_id')))
        courses = cursor.fetchall(); cursor.close(); connection.close()
        return render_template('teacher_bank_courses.html', courses=courses)
    return redirect(url_for('auth.login'))

@teacher.route('/question_bank/<string:course_code>')
def course_question_bank(course_code):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM courses WHERE course_code = %s", (course_code,))
        course = cursor.fetchone()
     
        cursor.execute("SELECT * FROM questions WHERE course_code = %s AND is_isolated = 0 AND teacher_id = %s", (course_code, session.get('user_id')))
        questions = cursor.fetchall()
        for q in questions:
            cursor.execute("SELECT * FROM options WHERE question_id = %s ", (q['question_id'],))
            q['options'] = cursor.fetchall()
        cursor.close(); connection.close()
        return render_template('teacher_bank_details.html', course=course, questions=questions)
    return redirect(url_for('auth.login'))

@teacher.route('/my_courses')
def my_courses():
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT c.*, cl.class_code, b.block_name, b.program_id, p.program_name
            FROM courses c 
            JOIN classes cl ON c.course_code = cl.course_code 
            JOIN blocks b ON cl.block_id = b.block_id
            JOIN programs p ON p.program_id = b.program_id
            WHERE cl.teacher_id = %s
        """, (session.get('user_id'),))
        courses = cursor.fetchall()
        cursor.close()
        connection.close()
        return render_template('teacher_my_courses.html', courses=courses)
    return redirect(url_for('auth.login'))

@teacher.route('/exam_analysis')
def exam_analysis():
    if not teacher_logged_in(): 
        return redirect(url_for('auth.login'))
    
    teacher_id = session.get('user_id')
    exam_id = request.args.get('exam_id', type=int)
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT e.exam_id, e.title, c.course_name 
            FROM exams e 
            JOIN classes cl ON e.class_code = cl.class_code 
            JOIN courses c ON cl.course_code = c.course_code 
            WHERE cl.teacher_id = %s AND e.archived = 0
        """, (teacher_id,))
        all_exams = cursor.fetchall()

        selected_exam = None
        stats = {}
        rankings = []
        item_analysis = []

        if exam_id:
            cursor.execute("SELECT * FROM exams WHERE exam_id = %s", (exam_id,))
            selected_exam = cursor.fetchone()

            if selected_exam:
                passing_threshold = float(selected_exam['question_limit']) * (float(selected_exam['pass_percentage']) / 100)

                cursor.execute("""
                    SELECT 
                        COUNT(attempt_id) as total_takers,
                        AVG(score) as avg_raw_score,
                        SUM(tab_switches) as total_violations,
                        SUM(CASE WHEN score >= %s THEN 1 ELSE 0 END) as passed_count
                    FROM exam_attempts 
                    WHERE exam_id = %s AND status = 'finished'
                """, (passing_threshold, exam_id))
                summary = cursor.fetchone()
                
                if summary and summary['total_takers'] > 0:
                    stats = {
                        'total_takers': summary['total_takers'],
                        'avg_percent': round((summary['avg_raw_score'] / selected_exam['question_limit']) * 100, 1) if summary['avg_raw_score'] else 0,
                        'pass_rate': round((summary['passed_count'] / summary['total_takers']) * 100, 1),
                        'violations': summary['total_violations'] or 0
                    }

                    cursor.execute("""
                        SELECT s.firstname, s.lastname, ea.score, ea.attempt_id,
                               round((ea.score / %s) * 100, 1) as percentage
                        FROM exam_attempts ea
                        JOIN students s ON ea.student_id = s.student_id
                        WHERE ea.exam_id = %s AND ea.status = 'finished'
                        ORDER BY ea.score DESC, ea.end_time ASC
                        LIMIT 10
                    """, (selected_exam['question_limit'], exam_id))
                    rankings = cursor.fetchall()

                    # FETCH ALL ITEMS (for modal), ORDER BY FAIL RATE
                    cursor.execute("""
                        SELECT 
                            q.question_text, 
                            COUNT(sa.answer_id) as total,
                            SUM(CASE WHEN sa.is_correct = 1 THEN 1 ELSE 0 END) as correct_count,
                            SUM(CASE WHEN sa.is_correct = 0 THEN 1 ELSE 0 END) as incorrect_count
                        FROM attempt_questions aq
                        JOIN questions q ON aq.question_id = q.question_id
                        LEFT JOIN student_answers sa ON q.question_id = sa.question_id AND sa.attempt_id = aq.attempt_id
                        WHERE aq.attempt_id IN (SELECT attempt_id FROM exam_attempts WHERE exam_id = %s AND status='finished')
                        GROUP BY q.question_id
                        ORDER BY incorrect_count DESC
                    """, (exam_id,))
                    items = cursor.fetchall()
                    
                    for item in items:
                        total = item['total']
                        item_analysis.append({
                            'text': item['question_text'],
                            'correct_p': round((item['correct_count'] / total) * 100, 1) if total > 0 else 0,
                            'incorrect_p': round((item['incorrect_count'] / total) * 100, 1) if total > 0 else 0,
                            'incorrect_count': item['incorrect_count']
                        })

        return render_template('teacher_analysis.html', 
                               all_exams=all_exams, 
                               selected_exam=selected_exam,
                               stats=stats,
                               rankings=rankings,
                               item_analysis=item_analysis) # This now contains the full list
    finally:
        cursor.close()
        connection.close()

#! 2. QUESTION BANK MANAGEMENT
@teacher.route('/add_bank_question/<string:course_code>', methods=['POST'])
def add_bank_question(course_code):
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        q_text, q_type, difficulty = request.form.get('question_text'), request.form.get('question_type'), request.form.get('difficulty')
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        try:
            cursor.execute("INSERT INTO questions (course_code, teacher_id, question_text, question_type, difficulty) VALUES (%s, %s, %s, %s, %s)", (course_code, teacher_id, q_text, q_type, difficulty))
            q_id = cursor.lastrowid
            if q_type == 'multiple_choice':
                options = request.form.getlist('options[]'); correct_idx = int(request.form.get('correct_option'))
                for i, opt in enumerate(options): cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, opt, 1 if i == correct_idx else 0))
            elif q_type == 'true_false':
                val = request.form.get('tf_correct')
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'True', 1 if val == 'True' else 0))
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'False', 1 if val == 'False' else 0))
            elif q_type == 'identification': cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, request.form.get('ident_answer'), 1))
            connection.commit()
        finally: cursor.close(); connection.close()
        return redirect(url_for('teacher.course_question_bank', course_code=course_code))
    return redirect(url_for('auth.login'))

@teacher.route('/delete_bank_question/<int:q_id>/<string:course_code>', methods=['POST'])
def delete_bank_question(q_id, course_code):
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        # Security: Delete only if teacher_id matches
        cursor.execute("DELETE FROM questions WHERE question_id = %s AND teacher_id = %s", (q_id, session.get('user_id'))); connection.commit()
        cursor.close(); connection.close()
        return redirect(url_for('teacher.course_question_bank', course_code=course_code))

@teacher.route('/bulk_delete_bank_questions/<string:course_code>', methods=['POST'])
def bulk_delete_bank_questions(course_code):
    if teacher_logged_in():
        ids = request.form.getlist('question_ids[]')
        if ids:
            connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
            query = "DELETE FROM questions WHERE question_id IN ({}) AND teacher_id = %s".format(','.join(['%s']*len(ids)))
            cursor.execute(query, tuple(ids) + (session.get('user_id'),)); connection.commit(); cursor.close(); connection.close()
        return redirect(url_for('teacher.course_question_bank', course_code=course_code))
    return redirect(url_for('auth.login'))

@teacher.route('/manage_exams')
def manage_exams():
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT e.*, c.course_name, cl.class_code, cl.course_code, b.block_name,
                (SELECT COUNT(*) FROM exam_questions WHERE exam_id = e.exam_id) as q_count,
                (SELECT COUNT(*) FROM exam_attempts WHERE exam_id = e.exam_id) as attempt_count
            FROM exams e 
            JOIN classes cl ON e.class_code = cl.class_code 
            JOIN courses c ON cl.course_code = c.course_code 
            JOIN blocks b ON cl.block_id = b.block_id
            WHERE cl.teacher_id = %s AND e.archived = 0
        """, (session.get('user_id'),))
        exams = cursor.fetchall()

        cursor.execute("""
            SELECT cl.class_code, c.course_name, cl.course_code, b.block_name, p.program_name
            FROM classes cl 
            JOIN courses c ON cl.course_code = c.course_code 
            JOIN blocks b ON cl.block_id = b.block_id
            JOIN programs p ON b.program_id = p.program_id
            WHERE cl.teacher_id = %s
        """, (session.get('user_id'),))
        classes = cursor.fetchall()

        classes_map = {c['class_code']: c for c in classes}

        cursor.close()
        connection.close()

        return render_template(
            'teacher_exams.html',
            exams=exams,
            classes=classes,
            classes_map=classes_map,
            now=datetime.now()
        )

    return redirect(url_for('auth.login'))

@teacher.route('/publish_exam_to_classes', methods=['POST'])
def publish_exam_to_classes():
    if not teacher_logged_in(): 
        return redirect(url_for('auth.login'))
    
    source_exam_id = request.form.get('source_exam_id')
    selected_class_codes = request.form.getlist('target_class_codes[]')
    
    if not selected_class_codes:
        flash("No target classes selected.", "warning")
        return redirect(url_for('teacher.manage_exams'))

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM exams WHERE exam_id = %s", (source_exam_id,))
        src = cursor.fetchone()
        
        if src:
            # Fix: Handle potentially empty datetime
            exam_schedule = src['date_time'] if src['date_time'] else None

            for class_code in selected_class_codes:
                cursor.execute("""
                    INSERT INTO exams (class_code, title, duration_minutes, pass_percentage, date_time, created_by, question_limit, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
                """, (class_code, src['title'], src['duration_minutes'], src['pass_percentage'], 
                      exam_schedule, session.get('user_id'), src['question_limit']))
                
                new_exam_id = cursor.lastrowid
                cursor.execute("""
                    INSERT INTO exam_questions (exam_id, question_id)
                    SELECT %s, question_id FROM exam_questions WHERE exam_id = %s
                """, (new_exam_id, source_exam_id))
            
            connection.commit()
            flash(f"Exam published successfully.", "success")
    except Exception as e:
        connection.rollback()
        flash(f"Error: {str(e)}", "danger")
    finally:
        cursor.close(); connection.close()
    return redirect(url_for('teacher.manage_exams'))

@teacher.route('/add_exam', methods=['POST'])
def add_exam():
    if teacher_logged_in():
        class_code = request.form.get('class_code'); title = request.form.get('title'); duration = request.form.get('duration')
        pass_percent = request.form.get('pass_percentage'); schedule = request.form.get('schedule'); q_limit = request.form.get('question_limit', 50)
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
        cursor.execute("INSERT INTO exams (class_code, title, duration_minutes, pass_percentage, date_time, created_by, question_limit, is_active) VALUES (%s, %s, %s, %s, %s, %s, %s, 0)", (class_code, title, duration, pass_percent, schedule, session.get('user_id'), q_limit))
        new_id = cursor.lastrowid; connection.commit(); cursor.close(); connection.close()
        return redirect(url_for('teacher.manage_questions', exam_id=new_id))
    return redirect(url_for('auth.login'))

@teacher.route('/update_exam', methods=['POST'])
def update_exam():
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    exam_id = request.form.get('exam_id'); status = request.form.get('status'); title = request.form.get('title'); duration = request.form.get('duration')
    pass_percent = request.form.get('pass_percentage'); schedule = request.form.get('schedule'); q_limit = request.form.get('question_limit')
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    if status == 'active':
        cursor.execute("SELECT COUNT(*) as count FROM exam_questions WHERE exam_id = %s", (exam_id,))
        if cursor.fetchone()['count'] == 0: flash("Empty exam pool.", "danger"); return redirect(url_for('teacher.manage_exams'))
    cursor.execute("UPDATE exams SET title=%s, duration_minutes=%s, pass_percentage=%s, is_active=%s, date_time=%s, question_limit=%s WHERE exam_id=%s", (title, duration, pass_percent, 1 if status=='active' else 0, schedule, q_limit, exam_id))
    connection.commit(); cursor.close(); connection.close()
    return redirect(url_for('teacher.manage_exams'))

@teacher.route('/delete_exam/<int:exam_id>', methods=['POST'])
def delete_exam(exam_id):
    """Handles direct deletion from the main management page if applicable."""
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    try:
        # 1. Delete isolated questions associated with this exam first
        cursor.execute("""
            DELETE FROM questions 
            WHERE is_isolated = 1 
            AND question_id IN (SELECT question_id FROM exam_questions WHERE exam_id = %s)
        """, (exam_id,))
        
        # 2. Delete the exam (This will CASCADE delete records in exam_questions and exam_attempts)
        cursor.execute("DELETE FROM exams WHERE exam_id = %s AND created_by = %s", (exam_id, session.get('user_id')))
        
        connection.commit()
        flash("Exam and its isolated questions deleted successfully.", "success")
    except Exception as e:
        connection.rollback()
        flash(f"Error deleting exam: {str(e)}", "danger")
    finally:
        cursor.close(); connection.close()
    return redirect(url_for('teacher.manage_exams'))

@teacher.route('/trashed_exams')
def trashed_exams():
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT e.*, c.course_name FROM exams e JOIN classes cl ON e.class_code = cl.class_code JOIN courses c ON cl.course_code = c.course_code WHERE cl.teacher_id = %s AND e.archived = 1", (session.get('user_id'),))
        exams = cursor.fetchall(); cursor.close(); connection.close()
        return render_template('teacher_trashed_exams.html', exams=exams)
    return redirect(url_for('auth.login'))

@teacher.route('/soft_delete_exam/<int:exam_id>', methods=['POST'])
def soft_delete_exam(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    cursor.execute("UPDATE exams SET archived = 1 WHERE exam_id = %s", (exam_id,)); connection.commit(); cursor.close(); connection.close()
    return redirect(url_for('teacher.manage_exams'))

@teacher.route('/restore_exam/<int:exam_id>', methods=['POST'])
def restore_exam(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    cursor.execute("UPDATE exams SET archived = 0 WHERE exam_id = %s", (exam_id,)); connection.commit(); cursor.close(); connection.close()
    return redirect(url_for('teacher.trashed_exams'))

@teacher.route('/delete_exam_permanently/<int:exam_id>', methods=['POST'])
def delete_exam_permanently(exam_id):
    """Handles permanent deletion from the Trash Bin."""
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    try:
        # 1. Find and delete isolated questions linked to this archived exam
        cursor.execute("""
            DELETE FROM questions 
            WHERE is_isolated = 1 
            AND question_id IN (SELECT question_id FROM exam_questions WHERE exam_id = %s)
        """, (exam_id,))
        
        # 2. Physically remove the exam record
        cursor.execute("DELETE FROM exams WHERE exam_id = %s AND created_by = %s", (exam_id, session.get('user_id')))
        
        connection.commit()
        flash("Exam permanently removed along with its isolated questions.", "success")
    except Exception as e:
        connection.rollback()
        flash(f"Error: {str(e)}", "danger")
    finally:
        cursor.close(); connection.close()
    return redirect(url_for('teacher.trashed_exams'))

@teacher.route('/empty_exam_trash', methods=['POST'])
def empty_exam_trash():
    """Bulk cleanup of all archived exams and their isolated questions."""
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    teacher_id = session.get('user_id')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    try:
        # 1. Delete all isolated questions belonging to any of this teacher's archived exams
        cursor.execute("""
            DELETE FROM questions 
            WHERE is_isolated = 1 
            AND question_id IN (
                SELECT eq.question_id 
                FROM exam_questions eq 
                JOIN exams e ON eq.exam_id = e.exam_id 
                WHERE e.archived = 1 AND e.created_by = %s
            )
        """, (teacher_id,))
        
        # 2. Delete all archived exams for this teacher
        cursor.execute("DELETE FROM exams WHERE archived = 1 AND created_by = %s", (teacher_id,))
        
        connection.commit()
        flash("Trash bin emptied. All isolated questions were also removed.", "success")
    except Exception as e:
        connection.rollback()
        flash(f"Error emptying trash: {str(e)}", "danger")
    finally:
        cursor.close(); connection.close()
    return redirect(url_for('teacher.trashed_exams'))

#! 4. EXAM QUESTIONS (POOL)
@teacher.route('/manage_questions/<int:exam_id>')
def manage_questions(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    # 1. Fetch Exam and Verify Ownership, including attempt_count for lockdown logic
    cursor.execute("""
        SELECT e.*, cl.course_code,
            (SELECT COUNT(*) FROM exam_attempts WHERE exam_id = e.exam_id) as attempt_count
        FROM exams e 
        JOIN classes cl ON e.class_code = cl.class_code 
        WHERE e.exam_id = %s AND cl.teacher_id = %s
    """, (exam_id, session.get('user_id')))
    exam = cursor.fetchone()
    
    if not exam:
        cursor.close(); connection.close()
        flash("Exam not found or unauthorized.", "danger")
        return redirect(url_for('teacher.manage_exams'))

    # 2. Fetch Questions linked to this Exam
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

    # 4. Fetch Master Bank questions (for the modal)
    cursor.execute("""
        SELECT * FROM questions 
        WHERE course_code = %s AND teacher_id = %s 
        AND question_id NOT IN (SELECT question_id FROM exam_questions WHERE exam_id = %s)
        AND is_isolated = 0
    """, (exam['course_code'], session.get('user_id'), exam_id))
    bank_questions = cursor.fetchall()
    
    for bq in bank_questions:
        cursor.execute("SELECT * FROM options WHERE question_id = %s", (bq['question_id'],))
        bq['options'] = cursor.fetchall()

    cursor.close(); connection.close()
    return render_template('teacher_questions.html', exam=exam, questions=questions, bank_questions=bank_questions)

def clone_exam_logic(old_exam_id, user_id):
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM exams WHERE exam_id = %s", (old_exam_id,))
        old_exam = cursor.fetchone()
        
        # Insert New Exam (is_active=0 as it is a draft)
        cursor.execute("""
            INSERT INTO exams (class_code, title, duration_minutes, pass_percentage, date_time, created_by, question_limit, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
        """, (old_exam['class_code'], f"{old_exam['title']} (Copy)", old_exam['duration_minutes'], 
              old_exam['pass_percentage'], old_exam['date_time'], user_id, old_exam['question_limit']))
        
        new_exam_id = cursor.lastrowid
        
        # Copy Question Links
        cursor.execute("""
            INSERT INTO exam_questions (exam_id, question_id)
            SELECT %s, question_id FROM exam_questions WHERE exam_id = %s
        """, (new_exam_id, old_exam_id))
        
        connection.commit()
        return new_exam_id
    finally:
        cursor.close()
        connection.close()

@teacher.route('/clone_exam/<int:exam_id>', methods=['POST'])
def duplicate_exam(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    try:
        new_id = clone_exam_logic(exam_id, session.get('user_id'))
        flash("Exam duplicated successfully. You can now modify the questions in this new draft.", "success")
        return redirect(url_for('teacher.manage_questions', exam_id=new_id))
    except Exception as e:
        flash(f"Error cloning exam: {str(e)}", "danger")
        return redirect(url_for('teacher.manage_exams'))

def is_exam_locked(exam_id):
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    # Check is_active (Active) and check for existing attempts (Finished/Has Data)
    cursor.execute("SELECT is_active FROM exams WHERE exam_id = %s", (exam_id,))
    exam = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) as attempts FROM exam_attempts WHERE exam_id = %s", (exam_id,))
    attempts = cursor.fetchone()['attempts']
    cursor.close()
    connection.close()
    
    if exam and exam['is_active'] == 1:
        return True, "Exam is currently active. Modifications are not allowed."
    if attempts > 0:
        return True, "This exam already has student submissions. Please duplicate the exam to make changes."
    return False, ""

@teacher.route('/add_question/<int:exam_id>', methods=['POST'])
def add_question(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    locked, msg = is_exam_locked(exam_id)
    if locked: 
        flash(msg, "danger")
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

    is_iso = 0 if request.form.get('save_to_bank') == 'on' else 1
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT cl.course_code FROM exams e JOIN classes cl ON e.class_code = cl.class_code WHERE e.exam_id = %s AND cl.teacher_id = %s", (exam_id, session.get('user_id')))
        res = cursor.fetchone()
        if not res: return "Unauthorized", 403
        
        course_code = res['course_code']; teacher_id = session.get('user_id')
        q_text = request.form.get('question_text'); q_type = request.form.get('question_type'); difficulty = request.form.get('difficulty')
        cursor.execute("INSERT INTO questions (course_code, teacher_id, question_text, question_type, difficulty, is_isolated) VALUES (%s, %s, %s, %s, %s, %s)", (course_code, teacher_id, q_text, q_type, difficulty, is_iso))
        q_id = cursor.lastrowid
        cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id))

        if q_type == 'multiple_choice':
            options = request.form.getlist('options[]'); correct_idx = int(request.form.get('correct_option'))
            for i, opt_text in enumerate(options):
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, opt_text, 1 if i == correct_idx else 0))
        elif q_type == 'true_false':
            val = request.form.get('tf_correct')
            cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'True', 1 if val == 'True' else 0))
            cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'False', 1 if val == 'False' else 0))
        elif q_type == 'identification':
            ans = request.form.get('ident_answer', '').strip()
            cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, ans, 1))
        connection.commit()
    finally: cursor.close(); connection.close()
    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))


@teacher.route('/delete_isolated_question/<int:q_id>/<int:exam_id>')
def delete_isolated_question(q_id, exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    locked, msg = is_exam_locked(exam_id)
    if locked:
        flash(msg, "danger"); return redirect(url_for('teacher.manage_questions', exam_id=exam_id))
        
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    cursor.execute("DELETE FROM questions WHERE question_id = %s AND is_isolated = 1", (q_id,))
    connection.commit(); cursor.close(); connection.close()
    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

@teacher.route('/import_ai_questions/<int:exam_id>', methods=['POST'])
def import_ai_questions(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    # 1. Lockdown Check (Reuse your existing locking logic)
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT is_active, (SELECT COUNT(*) FROM exam_attempts WHERE exam_id = %s) as attempt_count FROM exams WHERE exam_id = %s", (exam_id, exam_id))
    exam_status = cursor.fetchone()
    
    if exam_status['is_active'] == 1 or exam_status['attempt_count'] > 0:
        flash("Exam is locked. Cannot add questions.", "danger")
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

    # 2. Collect Form Data
    file = request.files.get('pdf_file')
    num_q = min(int(request.form.get('num_questions', 10)), 50) # Strict cap of 50
    teacher_notes = request.form.get('teacher_notes', 'General knowledge')
    save_to_bank = request.form.get('save_to_bank') == 'on'
    is_iso = 0 if save_to_bank else 1
    teacher_id = session.get('user_id')

    if not file or not file.filename.endswith('.pdf'):
        flash("Please upload a valid PDF file.", "danger")
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

    try:
        # 3. Get Course Code
        cursor.execute("SELECT cl.course_code FROM exams e JOIN classes cl ON e.class_code = cl.class_code WHERE e.exam_id = %s", (exam_id,))
        course_code = cursor.fetchone()['course_code']

        # 4. Extract Text from PDF
        raw_text = ""
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                raw_text += (page.extract_text() or "")
        
        # 5. Prompt Gemini with strict JSON requirement
        prompt = f"""
        ### ROLE
        Act as an expert academic assessment specialist. Generate exactly {num_q} high-quality questions based on the provided text and these specific requirements: "{teacher_notes}".

        ### CORE RULES
        1. **Allowed Types**: `multiple_choice`, `true_false`, `identification`.
        2. **Difficulty**: Assign 'easy', 'medium', or 'hard' based on conceptual depth (Bloom’s Taxonomy), not length or vocabulary.
        3. **Paraphrase**: Never copy verbatim. Rephrase concepts to test understanding rather than rote memorization.
        4. **No Meta-References**: Do not mention the text structure, page numbers, "the author," or "the passage." Questions must stand alone.
        5. **No Hallucinated Content**: All questions must be strictly derived from the provided source material. Do not invent facts, details, or concepts that are not explicitly supported by the input.

        ### QUESTION-SPECIFIC LOGIC
        - **multiple_choice**: Exactly 4 plausible options. No "all of the above" or joke answers. Only 1 correct answer.
        - **true_false**: Must be a definitive factual claim. Avoid "trick" phrasing or nuance that makes it subjective.
        - **identification**: Answer must be a single word or a short academic phrase.

        ### OUTPUT REQUIREMENTS
        - Return ONLY a raw JSON array. 
        - No markdown formatting, no ```json blocks, no introductory text. 
        - If the pdf's content is empty, return an empty array `[]`.

        ### JSON SCHEMA
        [
        {{
            "text": "The question content",
            "type": "multiple_choice | true_false | identification",
            "diff": "easy | medium | hard",
            "answer": "The correct answer string",
            "options": ["Option A", "Option B", "Option C", "Option D"] // null for other types
        }}
        ]

        ### SOURCE TEXT
    {raw_text[:10000]}
    """
        response = ai_model.generate_content(prompt)
        # Clean potential markdown backticks from AI response
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        questions_list = json.loads(clean_json)

        # 6. Database Insertion Loop
        for q in questions_list:
            cursor.execute("""
                INSERT INTO questions (course_code, teacher_id, question_text, question_type, difficulty, is_isolated) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (course_code, teacher_id, q['text'], q['type'], q['diff'], is_iso))
            
            q_id = cursor.lastrowid
            cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id))

            if q['type'] == 'multiple_choice':
                for opt in q['options']:
                    cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", 
                                   (q_id, opt, 1 if opt == q['answer'] else 0))
            elif q['type'] == 'true_false':
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'True', 1 if q['answer'].lower() == 'true' else 0))
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'False', 1 if q['answer'].lower() == 'false' else 0))
            elif q['type'] == 'identification':
                cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, q['answer'], 1))

        connection.commit()
        flash(f"AI successfully generated {len(questions_list)} questions!", "success")

    except Exception as e:
        connection.rollback()
        flash(f"AI Generation Error: {str(e)}", "danger")
    finally:
        cursor.close(); connection.close()

    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

@teacher.route('/download_template')
def download_template():
    if not teacher_logged_in():
        return redirect(url_for('auth.login'))
    
    from flask import current_app
    file_path = os.path.join(current_app.root_path, 'static', 'templates', 'TEMPLATE TESTPOINT.xlsx')
    
    if os.path.exists(file_path):
        return send_file(
            file_path,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name="TestPoint_Import_Template.xlsx"
        )
    else:
        flash("Template file not found on the server.", "danger")
        return redirect(request.referrer or url_for('teacher.teacher_dashboard'))

@teacher.route('/import_questions', methods=['POST'])
def import_questions():
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    exam_id = request.form.get('exam_id')
    
    if exam_id:
        locked, msg = is_exam_locked(exam_id)
        if locked:
            flash(msg, "danger")
            return redirect(request.referrer)

    file = request.files.get('excel_file'); save_to_bank = request.form.get('save_to_bank') == 'on'
    is_iso = 0 if (not exam_id or save_to_bank) else 1
    if file:
        try:
            df = pd.read_excel(file).fillna('')
            connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
            for _, row in df.iterrows():
                cursor.execute("INSERT INTO questions (course_code, teacher_id, question_text, question_type, difficulty, is_isolated) VALUES (%s, %s, %s, %s, %s, %s)", (request.form.get('course_code'), session.get('user_id'), str(row['Question']), str(row['Type']), str(row['Difficulty']), is_iso))
                q_id = cursor.lastrowid
                if exam_id and str(exam_id).strip(): cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id))
                ans = str(row['Answer']).strip(); q_type = str(row['Type']).lower()
                if q_type == 'multiple_choice':
                    for o in [str(row['OptA']), str(row['OptB']), str(row['OptC']), str(row['OptD'])]:
                        if o.strip(): cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, o, 1 if o.strip() == ans else 0))
                elif q_type == 'true_false':
                    cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'True', 1 if ans.lower() == 'true' else 0))
                    cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, 'False', 1 if ans.lower() == 'false' else 0))
                elif q_type == 'identification': cursor.execute("INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)", (q_id, ans, 1))
            connection.commit(); cursor.close(); connection.close(); flash("Import successful!", "success")
        except Exception as e: flash(f"Import Error: {e}", "danger")
    return redirect(request.referrer)


@teacher.route('/link_from_bank/<int:exam_id>/<int:q_id>', methods=['POST'])
def link_from_bank(exam_id, q_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    locked, msg = is_exam_locked(exam_id)
    if locked:
        flash(msg, "danger"); return redirect(url_for('teacher.manage_questions', exam_id=exam_id))
    
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    cursor.execute("INSERT IGNORE INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id))
    connection.commit(); cursor.close(); connection.close()
    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

@teacher.route('/bulk_link_from_bank/<int:exam_id>', methods=['POST'])
def bulk_link_from_bank(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    q_ids = request.form.getlist('bank_q_ids[]')
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    for q_id in q_ids: cursor.execute("INSERT IGNORE INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (exam_id, q_id))
    connection.commit(); cursor.close(); connection.close()
    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

@teacher.route('/bulk_unlink_questions/<int:exam_id>', methods=['POST'])
def bulk_unlink_questions(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    q_ids = request.form.getlist('question_ids[]')
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    for q_id in q_ids: cursor.execute("DELETE FROM exam_questions WHERE exam_id = %s AND question_id = %s", (exam_id, q_id))
    connection.commit(); cursor.close(); connection.close()
    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))


@teacher.route('/exam/<int:exam_id>/questions/bulk_action', methods=['POST'])
def bulk_question_action(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    
    locked, msg = is_exam_locked(exam_id)
    if locked:
        flash(msg, "danger")
        return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

    action = request.form.get('action'); question_ids = request.form.getlist('question_ids[]')
    if not question_ids: return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    try:
        format_strings = ','.join(['%s'] * len(question_ids))
        if action == 'unlink':
            query = f"DELETE eq FROM exam_questions eq JOIN questions q ON eq.question_id = q.question_id WHERE eq.exam_id = %s AND eq.question_id IN ({format_strings}) AND q.is_isolated = 0"
            cursor.execute(query, [exam_id] + question_ids)
            flash(f"Unlinked {cursor.rowcount} Bank questions.", "success")
        elif action == 'delete':
            query = f"DELETE FROM questions WHERE question_id IN ({format_strings}) AND is_isolated = 1"
            cursor.execute(query, question_ids)
            flash(f"Deleted {cursor.rowcount} isolated questions.", "danger")
        connection.commit()
    except Exception as e:
        connection.rollback(); flash(f"Error: {str(e)}", "error")
    finally: cursor.close(); connection.close()
    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))


@teacher.route('/delete_question/<int:q_id>/<int:exam_id>')
def delete_question(q_id, exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    locked, msg = is_exam_locked(exam_id)
    if locked:
        flash(msg, "danger"); return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    cursor.execute("DELETE FROM exam_questions WHERE question_id = %s AND exam_id = %s", (q_id, exam_id))
    connection.commit(); cursor.close(); connection.close()
    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

@teacher.route('/export_bank_questions/<string:course_code>')
def export_bank_questions(course_code):
    if not teacher_logged_in():
        return redirect(url_for('auth.login'))
    
    teacher_id = session.get('user_id')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    try:
        # 1. Fetch all bank questions for this course
        cursor.execute("""
            SELECT question_id, question_text, question_type, difficulty 
            FROM questions 
            WHERE course_code = %s AND teacher_id = %s AND is_isolated = 0
        """, (course_code, teacher_id))
        questions = cursor.fetchall()

        export_data = []

        for q in questions:
            # 2. Fetch options for each question
            cursor.execute("SELECT option_text, is_correct FROM options WHERE question_id = %s", (q['question_id'],))
            options = cursor.fetchall()

            row = {
                'Question': q['question_text'],
                'Type': q['question_type'],
                'Difficulty': q['difficulty'],
                'Answer': '',
                'OptA': '',
                'OptB': '',
                'OptC': '',
                'OptD': ''
            }

            if q['question_type'] == 'multiple_choice':
                for i, opt in enumerate(options):
                    letter = chr(65 + i) # A, B, C, D
                    if i < 4:
                        row[f'Opt{letter}'] = opt['option_text']
                    if opt['is_correct']:
                        row['Answer'] = opt['option_text']

            elif q['question_type'] == 'true_false':
                for opt in options:
                    if opt['is_correct']:
                        row['Answer'] = opt['option_text']

            elif q['question_type'] == 'identification':
                if options:
                    row['Answer'] = options[0]['option_text']

            export_data.append(row)

        # 3. Create Excel in memory
        df = pd.DataFrame(export_data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Questions')
        
        output.seek(0)
        
        filename = f"Bank_{course_code}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        flash(f"Export Error: {str(e)}", "danger")
        return redirect(url_for('teacher.course_question_bank', course_code=course_code))
    finally:
        cursor.close()
        connection.close()

#! 5. ENROLLEE MANAGEMENT
@teacher.route('/manage_enrollees/<string:class_code>')
def manage_enrollees(class_code):
    if not teacher_logged_in(): 
        return redirect(url_for('auth.login'))
        
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    try:
        # 1. Fetch Course and Class Metadata
        cursor.execute("""
            SELECT c.*, cl.class_code, b.block_name, b.program_id, p.program_name
            FROM classes cl
            JOIN courses c ON cl.course_code = c.course_code
            JOIN blocks b ON cl.block_id = b.block_id
            JOIN programs p ON p.program_id = b.program_id
            WHERE cl.class_code = %s AND cl.teacher_id = %s
        """, (class_code, session.get('user_id')))
        course = cursor.fetchone()

        if not course:
            flash("Class not found.", "danger")
            return redirect(url_for('teacher.my_courses'))

        # 2. Fetch Exams specifically for this class
        cursor.execute("""
            SELECT e.*, 
                (SELECT COUNT(*) FROM exam_questions WHERE exam_id = e.exam_id) as q_count,
                (SELECT COUNT(*) FROM exam_attempts WHERE exam_id = e.exam_id) as attempt_count
            FROM exams e 
            WHERE e.class_code = %s AND e.archived = 0
        """, (class_code,))
        class_exams = cursor.fetchall()

        # 3. Fetch Enrolled Students
        cursor.execute("""
            SELECT s.student_id, s.firstname, s.lastname, s.email,
                   CONCAT(p.program_name, ' - ', b.block_name) AS academic_block
            FROM enrollments e 
            JOIN students s ON e.student_id = s.student_id 
            LEFT JOIN blocks b ON s.block_id = b.block_id
            LEFT JOIN programs p ON b.program_id = p.program_id
            WHERE e.class_code = %s
            ORDER BY s.lastname ASC
        """, (class_code,))
        enrollees = cursor.fetchall()
        
        return render_template('teacher_enrollees.html', 
                               course=course, 
                               class_exams=class_exams, 
                               enrollees=enrollees, 
                               class_code=class_code)
    finally:
        cursor.close()
        connection.close()

#! 6. MONITORING & RESULTS
@teacher.route('/student_monitor')
def student_monitor():
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    # Updated query to get the LATEST latitude and longitude for each attempt
    query = """
        SELECT 
            ea.*, s.firstname, s.lastname, ex.title,
            vl.latitude, vl.longitude
        FROM exam_attempts ea 
        JOIN students s ON ea.student_id = s.student_id 
        JOIN exams ex ON ea.exam_id = ex.exam_id 
        JOIN classes cl ON ex.class_code = cl.class_code 
        LEFT JOIN (
            SELECT attempt_id, latitude, longitude
            FROM violation_logs
            WHERE log_id IN (SELECT MAX(log_id) FROM violation_logs GROUP BY attempt_id)
        ) vl ON ea.attempt_id = vl.attempt_id
        WHERE cl.teacher_id = %s AND ea.status = 'in-progress'
    """
    
    cursor.execute(query, (session.get('user_id'),))
    attempts = cursor.fetchall()
    cursor.close()
    connection.close()
    return render_template('teacher_monitor.html', attempts=attempts)

@teacher.route('/exam_results/<int:exam_id>')
def exam_results(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    teacher_id = session.get('user_id')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT e.*, c.course_name 
            FROM exams e
            JOIN classes cl ON e.class_code = cl.class_code
            JOIN courses c ON cl.course_code = c.course_code
            WHERE e.exam_id = %s AND cl.teacher_id = %s
        """, (exam_id, teacher_id))
        exam = cursor.fetchone()
        
        
        if not exam:
            flash("Exam not found or access denied.", "danger")
            return redirect(url_for('teacher.manage_exams'))

        cursor.execute("""
            SELECT 
                s.student_id, s.firstname, s.lastname,
                ea.attempt_id, ea.score, ea.status as attempt_status, ea.tab_switches,
                (SELECT COUNT(*) FROM exam_questions WHERE exam_id = %s) as total_questions
            FROM enrollments en
            JOIN students s ON en.student_id = s.student_id
            LEFT JOIN exam_attempts ea ON s.student_id = ea.student_id AND ea.exam_id = %s
            WHERE en.class_code = %s
            ORDER BY s.lastname ASC
        """, (exam_id, exam_id, exam['class_code']))
        results = cursor.fetchall()
        
        now = datetime.now()
        exam_end_time = exam['date_time'] + timedelta(minutes=exam['duration_minutes']) if exam['date_time'] else None
        is_past_due = (now > exam_end_time) if exam_end_time else False

        return render_template('teacher_exam_results.html', exam=exam, results=results, is_past_due=is_past_due, now=now)
    finally:
        cursor.close(); connection.close()

        
@teacher.route('/toggle_block_student/<string:student_id>/<int:exam_id>', methods=['POST'])
def toggle_block_student(student_id, exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    # Check if an attempt record already exists for this specific exam
    cursor.execute("SELECT status FROM exam_attempts WHERE student_id = %s AND exam_id = %s", (student_id, exam_id))
    attempt = cursor.fetchone()
    
    if attempt:
        if attempt['status'] == 'blocked':
            # Unblock: Since we want them to be able to take it, we can just delete the blocked record
            cursor.execute("DELETE FROM exam_attempts WHERE student_id = %s AND exam_id = %s", (student_id, exam_id))
            flash("Student has been unblocked from this exam.", "success")
        else:
            # Block: Change existing status to blocked
            cursor.execute("UPDATE exam_attempts SET status = 'blocked' WHERE student_id = %s AND exam_id = %s", (student_id, exam_id))
            flash("Student has been blocked from this exam.", "warning")
    else:
        # Create a new attempt record with status 'blocked'
        cursor.execute("INSERT INTO exam_attempts (student_id, exam_id, status) VALUES (%s, %s, 'blocked')", (student_id, exam_id))
        flash("Student has been blocked from this exam.", "warning")
        
    connection.commit()
    cursor.close(); connection.close()
    return redirect(url_for('teacher.exam_results', exam_id=exam_id))


@teacher.route('/update_exam_schedule/<int:exam_id>', methods=['POST'])
def update_exam_schedule(exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    new_time = request.form.get('new_time')
    new_duration = request.form.get('new_duration')
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    cursor.execute("UPDATE exams SET date_time = %s, duration_minutes = %s WHERE exam_id = %s", (new_time, new_duration, exam_id))
    connection.commit()
    cursor.close()
    connection.close()
    flash("Exam schedule updated successfully.", "success")
    return redirect(url_for('teacher.exam_results', exam_id=exam_id))

# Updated Reset Route: Redirects to the correct exam_results route
@teacher.route('/reset_exam/<int:attempt_id>/<int:exam_id>', methods=['POST'])
def reset_exam(attempt_id, exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    cursor.execute("DELETE FROM exam_attempts WHERE attempt_id = %s", (attempt_id,))
    connection.commit()
    cursor.close()
    connection.close()
    # Redirect to the route that provides the 'exam' object
    return redirect(url_for('teacher.exam_results', exam_id=exam_id))

@teacher.route('/teacher_review/<int:attempt_id>')
def teacher_review(attempt_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT q.*, sa.submitted_answer FROM questions q JOIN attempt_questions aq ON q.question_id = aq.question_id LEFT JOIN student_answers sa ON q.question_id = sa.question_id WHERE aq.attempt_id = %s", (attempt_id,))
    questions = cursor.fetchall(); cursor.close(); connection.close()
    return render_template('teacher_review_attempt.html', questions=questions)

@teacher.route('/review_student_attempt/<int:attempt_id>')
def review_student_attempt(attempt_id):
    if not teacher_logged_in(): 
        return redirect(url_for('auth.login'))
    
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True, buffered=True)
    
    try:
        cursor.execute("""
            SELECT ea.*, s.firstname, s.lastname, e.title, e.pass_percentage 
            FROM exam_attempts ea 
            JOIN students s ON ea.student_id = s.student_id 
            JOIN exams e ON ea.exam_id = e.exam_id 
            WHERE ea.attempt_id = %s
        """, (attempt_id,))
        attempt = cursor.fetchone()

        if not attempt:
            flash("Attempt not found.", "danger")
            return redirect(url_for('teacher.manage_exams'))

        cursor.execute("""
            SELECT q.*, sa.submitted_answer, sa.is_correct 
            FROM questions q 
            JOIN attempt_questions aq ON q.question_id = aq.question_id 
            LEFT JOIN student_answers sa ON q.question_id = sa.question_id AND sa.attempt_id = %s 
            WHERE aq.attempt_id = %s
        """, (attempt_id, attempt_id))
        questions = cursor.fetchall()

        for q in questions:
            cursor.execute("SELECT * FROM options WHERE question_id = %s", (q['question_id'],))
            q['options'] = cursor.fetchall()

        # Fetch logs including Latitude and Longitude
        cursor.execute("""
            SELECT violation_type, violation_time, latitude, longitude 
            FROM violation_logs 
            WHERE attempt_id = %s 
            ORDER BY violation_time ASC
        """, (attempt_id,))
        violation_logs = cursor.fetchall()

        return render_template('teacher_review_attempt.html', 
                               attempt=attempt, 
                               questions=questions, 
                               violation_logs=violation_logs)
    finally:
        cursor.close(); connection.close()

#! 7. PROFILE
@teacher.route('/profile', methods=['GET', 'POST'])
def profile():
    if not teacher_logged_in():
        return redirect(url_for('auth.login'))
        
    user_id = session.get('user_id')
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    try:
        if request.method == 'POST':
            # Handle profile update logic (keeping your existing logic)
            firstname = request.form.get('firstname')
            middlename = request.form.get('middlename')
            lastname = request.form.get('lastname')
            cursor.execute("""
                UPDATE teachers SET firstname = %s, middlename = %s, lastname = %s 
                WHERE teacher_id = %s
            """, (firstname, middlename, lastname, user_id))
            connection.commit()
            flash("Profile updated successfully.", "success")

        # 1. Fetch Detailed Teacher Info
        cursor.execute("""
            SELECT t.*, u.created_at, u.email 
            FROM teachers t 
            JOIN users u ON t.teacher_id = u.user_id 
            WHERE t.teacher_id = %s
        """, (user_id,))
        user = cursor.fetchone()

        # 2. Analytics: Active Classes Count
        cursor.execute("SELECT COUNT(*) as count FROM classes WHERE teacher_id = %s AND is_active = 1", (user_id,))
        class_count = cursor.fetchone()['count']

        # 3. Analytics: Question Bank Size
        cursor.execute("SELECT COUNT(*) as count FROM questions WHERE teacher_id = %s AND is_isolated = 0", (user_id,))
        pool_size = cursor.fetchone()['count']

        # 4. Analytics: Student Reach (Unique students across all classes)
        cursor.execute("""
            SELECT COUNT(DISTINCT e.student_id) as count 
            FROM enrollments e 
            JOIN classes cl ON e.class_code = cl.class_code 
            WHERE cl.teacher_id = %s
        """, (user_id,))
        student_reach = cursor.fetchone()['count']

        return render_template('teacher_profile.html', 
                               user=user, 
                               class_count=class_count, 
                               pool_size=pool_size, 
                               student_reach=student_reach)
    finally:
        cursor.close()
        connection.close()