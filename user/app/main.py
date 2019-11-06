from flask import render_template, url_for, session
from app import webapp


@webapp.route('/')
def main():
    #clear session in order to avoid information stored in the previous session
    if 'authenticated' in session:
        if not session['authenticated']:
            session.clear()
    return render_template("welcome.html")
