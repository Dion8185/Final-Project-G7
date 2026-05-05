# Final-Project-G7
Final Project in IT2206 and IT2211

This is a comprehensive README.md documentation for your TestPoint Online
Examination System. It covers the architecture, features, installation, and
specific role-based functionalities.

📑 TestPoint: Online Examination System

TestPoint is a robust, full-stack academic assessment platform built with Python
(Flask) and MySQL. It is designed to facilitate secure, high-integrity
examinations while providing powerful analytics for both educators and students.
It features multi-role access, AI-powered question generation, and real-time
proctoring mechanisms.

🚀 Key Technologies

  - Backend: Python 3.x, Flask
  - Database: MySQL
  - AI Integration: Google Gemini 1.5 Flash (for automated question generation)
  - Frontend: HTML5, CSS3 (SB Admin 2 / Bootstrap 4), JavaScript (jQuery)
  - Security: Scrypt password hashing, OTP Verification (Flask-Mail), PDF
    Verification, and Window-blur detection.
  - Libraries: Pandas (Excel processing), jsPDF (Certificate generation),
    Chart.js (Analytics), PDFPlumber (PDF text extraction).

🛠️ Installation & Setup

1. Prerequisites

  - Python 3.8+
  - MySQL Server
  - Gmail account (for SMTP OTP services)
  - Google Gemini API Key (for AI features)

2. Database Configuration

1.  Open your MySQL management tool (e.g., phpMyAdmin).
2.  Create a database named test_point.
3.  Import the provided test_point.sql file.

3. Environment Variables

Create a file named passwordDB.env inside the testpoint/ directory:

DBPASSWORD=your_mysql_password
GMAIL=your_email@gmail.com
GMAILPASS=your_app_specific_password
GEMINI_API_KEY=your_google_gemini_api_key

4. Setup Python Environment

# Clone the repository
git clone <your-repo-link>
cd TestPoint

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py

The system will be available at http://127.0.0.1:5000.

🎭 User Roles & Features

🛡️ 1. Administrator (The Command Center)

Administrators manage the institutional hierarchy and ensure the platform's
integrity.

  - Account Adjudication: Review registration requests, view uploaded PDF IDs,
    and Approve/Reject/Request resubmission from users.
  - Academic Structure: Manage Programs (e.g., BSIT), Blocks (Sections), and
    Subject Catalogs.
  - Class Scheduling: Link subjects, blocks, and teachers to create active Class
    Codes.
  - Oversight: Monitor all active examinations across the institution.
  - System Logs: Track user registration and activity timestamps.

🎓 2. Teacher (Assessment Engineering)

Teachers act as the primary creators and monitors of academic content.

  - AI Question Generator: Upload a PDF (module/handout), and the system uses
    Google Gemini AI to generate MCQs, T/F, or Identification questions
    automatically.
  - Master Question Bank: Build a reusable repository of questions categorized
    by course, difficulty, and type.
  - Exam Management: Create exams with specific duration, passing percentage,
    and question limits.
  - Live Proctoring: Monitor "Live Examinees" in real-time. The system logs
    every time a student switches tabs or leaves the exam window.
  - Detailed Audit: Review specific student attempts, see exactly which
    questions they missed, and what their submitted answers were.

✍️ 3. Student (Excellence & Performance)

Students focus on taking assessments within a high-security environment.

  - Lockdown Mode: Exams enforce mandatory fullscreen. Exiting fullscreen or
    blurring the window triggers a security violation logged for the teacher.
  - Exam Map: Navigate through questions with a visual indicator of answered,
    unanswered, and flagged items.
  - Auto-Save: Progress is saved via AJAX after every answer to prevent data
    loss on connection drops.
  - Academic Excellence Portal:
      - Certificates: Automatically generate professional-grade PDF certificates
        for ranking in the Top 3 of an exam.
      - Transcripts: Export a full academic performance report as a PDF.
  - Analytics: View performance trends over time and "Class Killer" item
    analysis (identifying the hardest concepts).

🔒 Security Features

  - Dual-Step Verification: Users must verify their email via a 6-digit OTP and
    then upload an institutional ID for manual admin review.
  - Exam Integrity:
      - Window Blur Detection: Detects if a user switches tabs or opens other
        apps.
      - Subset Randomization: The system can pull a random subset of questions
        (e.g., 20 questions from a 100-item pool) so no two students have the
        same exam.
      - Lockdown Middleware: Once an exam starts, Flask middleware prevents the
        student from accessing any other part of the site until submission.

📂 Project Structure

├── 📁 testpoint
│   ├── 📁 Admin       # Admin routes, logic, and templates
│   ├── 📁 Auth        # OTP, Login, Registration, and ID upload
│   ├── 📁 Student     # Exam taking, results, and certificate logic
│   ├── 📁 Teacher     # AI generation, Bank management, and Monitoring
│   ├── 📁 static      # Global CSS/JS and uploaded ID documents
│   └── 🐍 __init__.py # Flask app factory & DB config
├── 🐍 app.py          # Entry point
├── 📄 requirements.txt # Python dependencies
└── 📄 test_point.sql  # Database schema & seed data

📋 Database Schema Highlights

  - users: Central account table with role-based access.
  - pending_users: Temporary storage for accounts awaiting admin approval.
  - exams: Metadata for assessments including pass_percentage and
    question_limit.
  - exam_attempts: Tracks live session data, tab_switches, and scores.
  - questions / options: Recursive relationship supporting multiple question
    types.
  - attempt_questions: Junction table that handles the per-student
    randomization/shuffling.

📜 License

This project is developed for academic purposes. Distribution and use are
subject to institutional policies.

TestPoint Instructor & Student Systems © 2026
