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


#! 1. DASHBOARD & OVERVIEW
@teacher.route('/')
def teacher_dashboard():
    if teacher_logged_in():
        teacher_id = session.get('user_id')
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        try:
            # 1. Course Count
            cursor.execute("SELECT COUNT(DISTINCT course_code) as count FROM classes WHERE teacher_id = %s", (teacher_id,))
            course_count = cursor.fetchone()['count']

            # 2. Active Examinees
            cursor.execute("""
                SELECT COUNT(*) as count FROM exam_attempts ea 
                JOIN exams ex ON ea.exam_id = ex.exam_id 
                JOIN classes cl ON ex.class_code = cl.class_code 
                WHERE cl.teacher_id = %s AND ea.status = 'in-progress'
            """, (teacher_id,))
            active_examinees = cursor.fetchone()['count']
            
            # 3. Question Bank Count (Total Questions)
            cursor.execute("SELECT COUNT(*) as count FROM questions WHERE teacher_id = %s AND is_isolated = 0", (teacher_id,))
            total_q = cursor.fetchone()['count']

            # 4. Total Violations
            cursor.execute("""
                SELECT SUM(ea.tab_switches) as total FROM exam_attempts ea 
                JOIN exams ex ON ea.exam_id = ex.exam_id 
                JOIN classes cl ON ex.class_code = cl.class_code 
                WHERE cl.teacher_id = %s
            """, (teacher_id,))
            total_violations = cursor.fetchone()['total'] or 0

            # 5. Class Average
            cursor.execute("""
                SELECT AVG((ea.score / (SELECT COUNT(*) FROM exam_questions WHERE exam_id = ea.exam_id)) * 100) as avg_score
                FROM exam_attempts ea
                JOIN exams ex ON ea.exam_id = ex.exam_id
                JOIN classes cl ON ex.class_code = cl.class_code
                WHERE cl.teacher_id = %s AND ea.status = 'finished'
            """, (teacher_id,))
            class_avg = cursor.fetchone()['avg_score'] or 0

            # 6. Question Type Distribution
            cursor.execute("SELECT question_type, COUNT(*) as count FROM questions WHERE teacher_id = %s AND is_isolated = 0 GROUP BY question_type", (teacher_id,))
            dist_data = cursor.fetchall()
            type_mapping = {'multiple_choice': 'MCQ', 'true_false': 'T/F', 'identification': 'Ident.', 'essay': 'Essay'}
            dist_labels = [type_mapping.get(d['question_type'], d['question_type']) for d in dist_data]
            dist_values = [int(d['count']) for d in dist_data]

            # 7. Recent Submissions
            cursor.execute("""
                SELECT ea.score, s.firstname, s.lastname, ex.title, ea.end_time
                FROM exam_attempts ea
                JOIN students s ON ea.student_id = s.student_id
                JOIN exams ex ON ea.exam_id = ex.exam_id
                JOIN classes cl ON ex.class_code = cl.class_code
                WHERE cl.teacher_id = %s AND ea.status = 'finished'
                ORDER BY ea.end_time DESC LIMIT 5
            """, (teacher_id,))
            recent_submissions = cursor.fetchall()

            return render_template('teacher_dashboard.html', 
                                   firstname=session.get('firstname'), 
                                   course_count=course_count,
                                   active_examinees=active_examinees,
                                   total_q=total_q, 
                                   total_violations=total_violations, 
                                   class_avg=round(class_avg, 1), 
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
            SELECT c.*, cl.class_code, b.block_name 
            FROM courses c 
            JOIN classes cl ON c.course_code = cl.course_code 
            JOIN blocks b ON cl.block_id = b.block_id
            WHERE cl.teacher_id = %s
        """, (session.get('user_id'),))
        courses = cursor.fetchall()
        cursor.close()
        connection.close()
        return render_template('teacher_my_courses.html', courses=courses)
    return redirect(url_for('auth.login'))

@teacher.route('/exam_analysis')
def exam_analysis():
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT e.exam_id, e.title, c.course_name, COUNT(ea.attempt_id) as total_takers, AVG(ea.score) as average_score FROM exams e JOIN classes cl ON e.class_code = cl.class_code JOIN courses c ON cl.course_code = c.course_code LEFT JOIN exam_attempts ea ON e.exam_id = ea.exam_id AND ea.status = 'finished' WHERE cl.teacher_id = %s GROUP BY e.exam_id", (session.get('user_id'),))
    exams = cursor.fetchall(); cursor.close(); connection.close()
    return render_template('teacher_analysis.html', exams=exams)

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

#! 3. EXAM MANAGEMENT

@teacher.route('/manage_exams')
def manage_exams():
    if teacher_logged_in():
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        # FIXED QUERY: Added (SELECT COUNT(*) FROM exam_attempts...) as attempt_count
        cursor.execute("""
            SELECT e.*, c.course_name, cl.class_code, 
                (SELECT COUNT(*) FROM exam_questions WHERE exam_id = e.exam_id) as q_count,
                (SELECT COUNT(*) FROM exam_attempts WHERE exam_id = e.exam_id) as attempt_count
            FROM exams e 
            JOIN classes cl ON e.class_code = cl.class_code 
            JOIN courses c ON cl.course_code = c.course_code 
            WHERE cl.teacher_id = %s AND e.archived = 0
        """, (session.get('user_id'),))
        exams = cursor.fetchall()
        
        cursor.execute("""
            SELECT cl.class_code, c.course_name 
            FROM classes cl 
            JOIN courses c ON cl.course_code = c.course_code 
            WHERE cl.teacher_id = %s
        """, (session.get('user_id'),))
        classes = cursor.fetchall()
        
        cursor.close()
        connection.close()
        return render_template('teacher_exams.html', exams=exams, classes=classes, now=datetime.now())
    return redirect(url_for('auth.login'))

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
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    cursor.execute("DELETE FROM exams WHERE exam_id = %s", (exam_id,)); connection.commit(); cursor.close(); connection.close()
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
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    cursor.execute("DELETE FROM exams WHERE exam_id = %s", (exam_id,)); connection.commit(); cursor.close(); connection.close()
    return redirect(url_for('teacher.trashed_exams'))

@teacher.route('/empty_exam_trash', methods=['POST'])
def empty_exam_trash():
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    cursor.execute("DELETE FROM exams WHERE archived = 1 AND created_by = %s", (session.get('user_id'),)); connection.commit(); cursor.close(); connection.close()
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


@teacher.route('/delete_question/<int:q_id>/<int:exam_id>', methods=['POST'])
def delete_question(q_id, exam_id):
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    locked, msg = is_exam_locked(exam_id)
    if locked:
        flash(msg, "danger"); return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

    connection = mysql.connector.connect(**db_config); cursor = connection.cursor()
    cursor.execute("DELETE FROM exam_questions WHERE question_id = %s AND exam_id = %s", (q_id, exam_id))
    connection.commit(); cursor.close(); connection.close()
    return redirect(url_for('teacher.manage_questions', exam_id=exam_id))

#! 5. ENROLLEE MANAGEMENT
@teacher.route('/manage_enrollees/<string:class_code>')
def manage_enrollees(class_code):
    if not teacher_logged_in(): 
        return redirect(url_for('auth.login'))
        
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    try:
        # Concatenating Program Name and Block Name into one field
        cursor.execute("""
            SELECT 
                s.student_id, 
                s.firstname, 
                s.middlename, 
                s.lastname, 
                s.email,
                CONCAT(p.program_name, ' - ', b.block_name) AS academic_block
            FROM enrollments e 
            JOIN students s ON e.student_id = s.student_id 
            LEFT JOIN blocks b ON s.block_id = b.block_id
            LEFT JOIN programs p ON b.program_id = p.program_id
            WHERE e.class_code = %s
            ORDER BY s.lastname ASC
        """, (class_code,))
        enrollees = cursor.fetchall()
        
    finally:
        cursor.close()
        connection.close()
        
    return render_template('teacher_enrollees.html', class_code=class_code, enrollees=enrollees )

#! 6. MONITORING & RESULTS
@teacher.route('/student_monitor')
def student_monitor():
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT ea.*, s.firstname, s.lastname, ex.title FROM exam_attempts ea JOIN students s ON ea.student_id = s.student_id JOIN exams ex ON ea.exam_id = ex.exam_id JOIN classes cl ON ex.class_code = cl.class_code WHERE cl.teacher_id = %s AND ea.status = 'in-progress'", (session.get('user_id'),))
    attempts = cursor.fetchall(); cursor.close(); connection.close()
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

        # 2. Fetch Student Results
        cursor.execute("""
            SELECT ea.*, s.firstname, s.lastname, s.student_id,
                (SELECT COUNT(*) FROM attempt_questions WHERE attempt_id = ea.attempt_id) as total_questions
            FROM exam_attempts ea
            JOIN students s ON ea.student_id = s.student_id
            WHERE ea.exam_id = %s
            ORDER BY s.lastname ASC
        """, (exam_id,))
        results = cursor.fetchall()
        
        return render_template('teacher_exam_results.html', exam=exam, results=results)
    finally:
        cursor.close()
        connection.close()

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
        # 1. Fetch Attempt, Student, and Exam Metadata (including pass_percentage)
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

        # 2. Fetch questions served during this attempt along with the student's answer
        cursor.execute("""
            SELECT q.*, sa.submitted_answer, sa.is_correct 
            FROM questions q 
            JOIN attempt_questions aq ON q.question_id = aq.question_id 
            LEFT JOIN student_answers sa ON q.question_id = sa.question_id AND sa.attempt_id = %s 
            WHERE aq.attempt_id = %s
        """, (attempt_id, attempt_id))
        questions = cursor.fetchall()

        # 3. Fetch options for each question so we can show the correct answer
        for q in questions:
            cursor.execute("SELECT * FROM options WHERE question_id = %s", (q['question_id'],))
            q['options'] = cursor.fetchall()

        return render_template('teacher_review_attempt.html', attempt=attempt, questions=questions)
    
    finally:
        cursor.close()
        connection.close()

#! 7. PROFILE
@teacher.route('/profile', methods=['GET', 'POST'])
def profile():
    if not teacher_logged_in(): return redirect(url_for('auth.login'))
    user_id = session.get('user_id')
    connection = mysql.connector.connect(**db_config); cursor = connection.cursor(dictionary=True)
    if request.method == 'POST':
        cursor.execute("UPDATE teachers SET firstname = %s, middlename = %s, lastname = %s WHERE teacher_id = %s", (request.form.get('firstname'), request.form.get('middlename'), request.form.get('lastname'), user_id))
        connection.commit()
    cursor.execute("SELECT * FROM teachers WHERE teacher_id = %s", (user_id,))
    user = cursor.fetchone(); cursor.close(); connection.close()
    return render_template('teacher_profile.html', user=user)