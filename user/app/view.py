import os
import boto3
from flask import render_template, session, redirect, url_for
from app import webapp
from app.user_op_data import get_db

s3 = boto3.client("s3")

@webapp.route('/view', methods=['POST', 'GET'])
def view():
    if 'username' not in session:
        return redirect(url_for('user'))
    username = str(session['username'])
    cnx = get_db()
    cursor = cnx.cursor()

    query = "SELECT origin_path,thumb_path,text_path from user_information,image where image.user_id = user_information.user_id and username = '%s';" % username
    cursor.execute(query)
    allphotos = cursor.fetchall()

    if not allphotos:
        session['error_dis'] = "No photo in your account, Please upload photos first!"
        return redirect(url_for('disPhoto'))
    else:
        session['error_dis'] = None

# download user's all files to local
    for row in allphotos:
        for col in row:
            print(col[15:])
            s3.download_file('a2homework',col[16:], col[16:])

    listphoto = []
    #insert filename to form new list
    for row in allphotos:
        listtemp=[]
        for col in row:
            listtemp.append(col[16:])
            #print(listtemp)
            #print(row[1])
        fpath = os.path.split(row[1])
        listtemp.append(fpath[1])
        listphoto.append(listtemp)
        print(listphoto)

    return render_template('view.html', listphoto=listphoto)
