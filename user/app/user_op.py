from builtins import len

from flask import render_template, session, request, redirect, url_for
from app import webapp
from app.user_op_data import get_db
# password
from werkzeug.security import generate_password_hash, check_password_hash
from app.upload import file_uploadTA

webapp.secret_key = '\x80\xa9s*\x12\xc7x\xa9d\x1f(\x03\xbeHJ:\x9f\xf0!\xb1a\xaa\x0f\xee'


# transform password to salted password
def enPassWord(password):
    return generate_password_hash(password)


# compare the input password with encrypted password
def checkPassWord(enpassword, password):
    return check_password_hash(enpassword, password)

@webapp.route('/user')
def user():
    return render_template("user.html")

@webapp.route('/login', methods=['GET', 'POST'])
def login():
    uname = None
    e = None

    if 'username' in session:
        uname = session['username']

    if 'error' in session:
        e = session['error']

    if 'authenticated' in session:
        if session['authenticated']:
            return redirect(url_for('disPhoto'))

    return render_template("login.html", error=e, username=uname)


@webapp.route('/login_submit', methods=['POST'])
def login_submit():
    cnx = get_db()
    cursor = cnx.cursor()
    if 'username' in request.form and \
            'password' in request.form:
        query = "SELECT * FROM user_information WHERE username='%s';" % (request.form['username'])
        cursor.execute(query)
        c = cursor.fetchall()
        if len(c) == 1 and checkPassWord(c[0][2], request.form['password']):
            session['authenticated'] = True
            session.permanent = True
            session['username'] = request.form['username']
            session['error_dis'] = None
            session['user_id'] = c[0][0]
            login_success = 'You have successfully logged in!'
            return render_template("upload.html", login_success=login_success)

    if 'username' in request.form:
        session['username'] = request.form['username']
        session['authenticated'] = False

    session['error'] = "Error! Incorrect username or password!"
    return redirect(url_for('login'))

@webapp.route('/disPhoto')
def disPhoto():
    error_dis = None
    if 'error_dis' in session:
        error_dis = session['error_dis']
    return render_template("upload.html", error_dis=error_dis)

@webapp.route('/register', methods=['GET', 'POST'])
def register():
    uname_r = None
    e_r = None

    if 'username_r' in session:
        uname_r = session['username_r']

    if 'error_r' in session:
        e_r = session['error_r']

    return render_template("register.html", error=e_r, username=uname_r)


@webapp.route('/register_submit', methods=['POST'])
def register_submit():
    cnx = get_db()
    cursor = cnx.cursor()
    if 'username' in request.form and \
            'password' in request.form and \
            'confirm_password' in request.form:
        query = "SELECT * FROM user_information WHERE username='%s';" % (request.form['username'])
        cursor.execute(query)
        c = cursor.fetchall()
        # Judge if the username has duplicate
        if len(c) == 1 and c[0][1] == request.form['username']:
            session['error_r'] = "This user had registered, change another username!"
            return redirect(url_for('register'))
        # Judge if the username is longer than 100 chars
        if len(request.form['username']) >= 100:
            session['error_r'] = "Username is too long!"
            return redirect(url_for('register'))
        # Judge whether the two passwords are same
        if request.form['password'] != request.form['confirm_password']:
            session['error_r'] = "The two passwords are not the same, please confirm!"
            return redirect(url_for('register'))
        # Assign unique user_id
        query = "SELECT * FROM user_information";
        cursor.execute(query)
        c = cursor.fetchall()
        id = len(c)
        saltedPS = enPassWord(request.form['password'])
        query = "INSERT INTO user_information VALUES ('%d','%s','%s');" % (
            id + 1, request.form['username'], saltedPS)
        try:
            cursor.execute(query)
            cnx.commit()
        except:
            cnx.rollback()

        success = "Create account Success, please login!"
        return render_template("login.html", register_success=success)

    session['error_r'] = "Every box should have value!"
    return redirect(url_for('register'))


@webapp.route('/show', methods=['GET', 'POST'])
def show():
    return render_template("show.html")


@webapp.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    return render_template("base.html")


# Register for TA
@webapp.route('/api/register', methods=['POST'])
def registerTA():
    try:
        username = str(request.args.get('username'))
        password = str(request.args.get('password'))
        cnx = get_db()
        cursor = cnx.cursor()
        # Judge if the args are empty
        if len(username) == 0 or len(password) == 0:
            return "None of the username or password should be empty!"
        query = "SELECT * FROM user_information WHERE username='%s';" % (username)
        cursor.execute(query)
        c = cursor.fetchall()
        # Judge if the username has duplicate
        if len(c) == 1 and c[0][1] == username:
            return "This user had registered, change another username!"
        # Judge if the username is longer than 100 chars
        if len(username) >= 100:
            return "Username is too long!"
        # Assign unique user_id
        query = "SELECT * FROM user_information";
        cursor.execute(query)
        c = cursor.fetchall()
        id = len(c)
        saltedPS = enPassWord(password)
        query = "INSERT INTO user_information VALUES ('%d','%s','%s');" % (
            id + 1, username, saltedPS)
        try:
            cursor.execute(query)
            cnx.commit()
        except:
            cnx.rollback()
        return "Create account Success, please login!"
    except Exception as e:
        traceback.print_tb(e.__traceback__)
        return "Create new account failed!"


# Upload for TA
@webapp.route('/api/upload', methods=['POST'])
def uploadTA():
    username = request.values['username']
    password = request.values['password']
    message, permission = loginTA(username, password)
    if permission == 0:
        return message
    else:
        return file_uploadTA()


def loginTA(username, password):
    cnx = get_db()
    cursor = cnx.cursor()
    if len(username) == 0 or len(password) == 0:
        message = "None of the username and password should be empty!"
        permission = 0
    else:
        query = "SELECT * FROM user_information WHERE username='%s';" % (username)
        cursor.execute(query)
        c = cursor.fetchall()
        if len(c) == 1 and checkPassWord(c[0][2], password):
            session['authenticated'] = True
            session.permanent = True
            session['username'] = username
            session['user_id'] = c[0][0]
            message = "Login success!"
            permission = 1
        else:
            session['authenticated'] = False
            message = "Error! Incorrect username or password!"
            permission = 0
    return message, permission
