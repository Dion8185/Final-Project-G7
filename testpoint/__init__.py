from flask import Flask

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'test_point',
    'auth_plugin': 'mysql_native_password'
}

def create_app():

    app = Flask(__name__)
    app.secret_key = "Secret@123_key"
    
    from testpoint.Auth.login import auth, register
    from testpoint.Admin.admin import admin
    from testpoint.Student.student import student
    from testpoint.Teacher.teacher import teacher
    
    app.register_blueprint(auth)
    app.register_blueprint(register)
    app.register_blueprint(admin)
    app.register_blueprint(teacher)
    app.register_blueprint(student)
    
    return app