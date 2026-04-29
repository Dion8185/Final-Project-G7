from flask import Flask
from flask_mail import Mail
from dotenv import load_dotenv
import os

load_dotenv("testpoint/passwordDB.env")
passwordDB = os.getenv("DBPASSWORD")
emailpassword = os.getenv("GMAILPASS")
email = os.getenv("GMAIL")

if not passwordDB:
    raise ValueError("DBPASSWORD is not set in passwordDB.env")

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': passwordDB,
    'database': 'test_point',
    'auth_plugin': 'mysql_native_password'
}

mail = Mail()

def create_app():
    app = Flask(__name__)
    app.secret_key = "Secret@123_key"
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['MAIL_PORT'] = 465
    app.config['MAIL_USERNAME'] = email
    app.config['MAIL_PASSWORD'] = emailpassword
    app.config['MAIL_USE_TLS'] = False
    app.config['MAIL_USE_SSL'] = True
    
    mail.init_app(app)
    
    from testpoint.Auth.login import auth
    from testpoint.Admin.admin import admin
    from testpoint.Student.student import student
    from testpoint.Teacher.teacher import teacher
    
    app.register_blueprint(auth)
    app.register_blueprint(admin, url_prefix='/admin')
    app.register_blueprint(teacher, url_prefix='/teacher')
    app.register_blueprint(student, url_prefix='/student')

    return app