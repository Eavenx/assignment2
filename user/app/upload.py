import os
import boto3
from datetime import datetime
from pytz import timezone
from flask import render_template, request, session
from app import webapp, db
from user.app.user_op_data import get_db
from PIL import Image
import numpy as np
import argparse
import time
import cv2
from user.app.suppression import non_max_suppression

s3 = boto3.resource("s3")

# define a function to make direction
def mkdir(path):
    folder = os.path.exists(path)
    if not folder:
        os.makedirs(path)

class RequestPerMinute(db.Model):
    __tablename__ = 'requestperminute'
    requestid = db.Column(db.Integer, primary_key=True)
    instance_id = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime)  # A type for datetime.datetime() objects.

    def __repr__(self):
        return '<RequestPerMinute {}>'.format(self.instance_id)


def record_requests(instance_id):
    try:
        requests = RequestPerMinute(instance_id=instance_id,
                                    timestamp=datetime.now)  # (timezone(webapp.config['ZONE'])))
        db.session.add(requests)
        db.session.commit()
    except Exception as e:
        print(e)

@webapp.route('/upload', methods=['POST'])
# Upload a new file and store in the systems temp directory

def upload():
    # check if the post request has the file part
    record_requests(webapp.config['INSTANCE_ID'])
    if 'file' not in request.files:
        error_u = "Missing uploaded file"
        return render_template("upload.html", error_u=error_u)
    new_file = request.files['file']

    # if user does not select file, browser also
    # submit a empty part without filename
    if new_file.filename == '':
        error_u = "Missing uploaded file"
        return render_template("upload.html", error_u=error_u)

    if 'username' not in session:
        error_u = "You are not an authorized User. Please log in or register first."
        return render_template("user.html", error_u=error_u)

    # create a new path for each new user&photo
    username = str(session["username"])
    now = datetime.now()
    name, extn = new_file.filename.split('.')

    # Filter incorrect type of file
    ALLOWED_EXTENSIONS = ['png', 'jpg', 'jpeg', 'JPG', 'PNG', 'JPEG']
    if extn not in ALLOWED_EXTENSIONS:
        error_u = 'Incorrect file type'
        return render_template("upload.html", error_u=error_u)

    # Distinguish between duplicate files and save the file
    localtime = now.strftime('%H%M%S')
    filename = name + localtime
    path = os.path.join("app", "static", username)
    mkdir(path)
    path_origin = os.path.join(path, filename+'.'+ extn)
    fname = os.path.join(path, filename + '.' + extn)
    new_file.save(fname)

    # Filter unreasonable big file
    fsize = os.path.getsize(fname)
    fsize = fsize / float(1024 * 1024)
    if fsize > 100:
        error_u = 'Unexpected big file'
        return render_template("upload.html", error_u=error_u)

    # generate and save the thumbnail
    im = Image.open(fname)
    im.thumbnail((200,100))
    path_tn = os.path.join(path, filename+'_tn'+'.'+ extn)
    im.save(path_tn)

    # generate and save the result of text detection
    # construct the argument parser and parse the arguments
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--image", type=str,
                    help="path to input image")
    ap.add_argument("-east", "--east", type=str,
                    help="path to input EAST text detector")
    ap.add_argument("-c", "--min-confidence", type=float, default=0.5,
                    help="minimum probability required to inspect a region")
    ap.add_argument("-w", "--width", type=int, default=320,
                    help="resized image width (should be multiple of 32)")
    ap.add_argument("-e", "--height", type=int, default=320,
                    help="resized image height (should be multiple of 32)")
    args = vars(ap.parse_args())

    # load the input image and grab the image dimensions
    image = cv2.imread(fname)
    orig = image.copy()
    (H, W) = image.shape[:2]

    # set the new width and height and then determine the ratio in change
    # for both the width and height
    (newW, newH) = (args["width"], args["height"])
    rW = W / float(newW)
    rH = H / float(newH)

    # resize the image and grab the new image dimensions
    image = cv2.resize(image, (newW, newH))
    (H, W) = image.shape[:2]

    # define the two output layer names for the EAST detector model that
    # we are interested -- the first is the output probabilities and the
    # second can be used to derive the bounding box coordinates of text
    layerNames = [
        "feature_fusion/Conv_7/Sigmoid",
        "feature_fusion/concat_3"]

    # load the pre-trained EAST text detector
    # print("[INFO] loading EAST text detector...")
    net = cv2.dnn.readNet("app/frozen_east_text_detection.pb")

    # construct a blob from the image and then perform a forward pass of
    # the model to obtain the two output layer sets
    blob = cv2.dnn.blobFromImage(image, 1.0, (W, H),
                                 (123.68, 116.78, 103.94), swapRB=True, crop=False)
    start = time.time()
    net.setInput(blob)
    (scores, geometry) = net.forward(layerNames)
    end = time.time()

    # show timing information on text prediction
    # print("[INFO] text detection took {:.6f} seconds".format(end - start))

    # grab the number of rows and columns from the scores volume, then
    # initialize our set of bounding box rectangles and corresponding
    # confidence scores
    (numRows, numCols) = scores.shape[2:4]
    rects = []
    confidences = []

    # loop over the number of rows
    for y in range(0, numRows):
        # extract the scores (probabilities), followed by the geometrical
        # data used to derive potential bounding box coordinates that
        # surround text
        scoresData = scores[0, 0, y]
        xData0 = geometry[0, 0, y]
        xData1 = geometry[0, 1, y]
        xData2 = geometry[0, 2, y]
        xData3 = geometry[0, 3, y]
        anglesData = geometry[0, 4, y]

        # loop over the number of columns
        for x in range(0, numCols):
            # if our score does not have sufficient probability, ignore it
            if scoresData[x] < args["min_confidence"]:
                continue

            # compute the offset factor as our resulting feature maps will
            # be 4x smaller than the input image
            (offsetX, offsetY) = (x * 4.0, y * 4.0)

            # extract the rotation angle for the prediction and then
            # compute the sin and cosine
            angle = anglesData[x]
            cos = np.cos(angle)
            sin = np.sin(angle)

            # use the geometry volume to derive the width and height of
            # the bounding box
            h = xData0[x] + xData2[x]
            w = xData1[x] + xData3[x]

            # compute both the starting and ending (x, y)-coordinates for
            # the text prediction bounding box
            endX = int(offsetX + (cos * xData1[x]) + (sin * xData2[x]))
            endY = int(offsetY - (sin * xData1[x]) + (cos * xData2[x]))
            startX = int(endX - w)
            startY = int(endY - h)

            # add the bounding box coordinates and probability score to
            # our respective lists
            rects.append((startX, startY, endX, endY))
            confidences.append(scoresData[x])

    # apply non-maxima suppression to suppress weak, overlapping bounding
    # boxes
    boxes = non_max_suppression(np.array(rects), probs=confidences)

    # loop over the bounding boxes
    for (startX, startY, endX, endY) in boxes:
        # scale the bounding box coordinates based on the respective
        # ratios
        startX = int(startX * rW)
        startY = int(startY * rH)
        endX = int(endX * rW)
        endY = int(endY * rH)

        # draw the bounding box on the image
        cv2.rectangle(orig, (startX, startY), (endX, endY), (0, 255, 0), 2)

    # show the output image
    # cv2.imshow("Text Detection", orig)
    # cv2.waitKey(0)
    # save the new image in a new path
    path_td = os.path.join(path, filename + '_td' + '.' + extn)
    cv2.imwrite(path_td, orig)

    object = open(path_origin,'rb')
    s3.Bucket('a2homework').put_object(Key=path_origin, Body=object)
    object2 = open(path_tn, 'rb')
    s3.Bucket('a2homework').put_object(Key=path_tn, Body=object2)
    object3 = open(path_td, 'rb')
    s3.Bucket('a2homework').put_object(Key=path_td, Body=object3)

    os.remove(path_origin)
    os.remove(path_tn)
    os.remove(path_td)

    path_s3 = 's3://a2homework/'

    cnx = get_db()
    cursor = cnx.cursor()

    query = '''SELECT user_id FROM user_information WHERE username = %s'''
    cursor.execute(query, (username,))
    user_id = cursor.fetchall()
    print(user_id)
    if len(user_id) == 1:
        user_id = user_id[0][0]

    query = '''INSERT INTO image VALUES (%s,%s,%s,%s)'''
    cursor.execute(query, (user_id, path_s3+path_origin, path_s3+path_tn, path_s3+path_td))
    cnx.commit()

    success_message = "Upload Succeed!"
    return render_template("upload.html", success_message = success_message)


@webapp.route('/<filename>')
def showphoto(filename):
    cnx = get_db()
    cursor = cnx.cursor()
    #query = "SELECT * from image where user_id=%s;" % (session['user_id'])
    #cursor.execute(query)
    #temp = cursor.fetchall()
    #pathhead = os.path.split(temp[0][2])
    #searchpath = os.path.join(pathhead[0], filename)
    #print(searchpath)
    query = "SELECT * from image where thumb_path like '%s';" % ('%' + filename)
    cursor.execute(query)
    result = cursor.fetchall()
    return render_template("album.html",
                           f1=result[0][1][20:], f2=result[0][2][20:], f3=result[0][3][20:])


def file_uploadTA():
    # check if the post request has the file part
    if 'file' not in request.files:
        return "Missing uploaded file"

    new_file = request.files['file']


    # if user does not select file, browser also
    # submit a empty part without filename
    if new_file.filename == '':
        return 'Missing file name'

    # create a new path for each new user&photo
    username = str(session["username"])
    now = datetime.now()
    name, extn = new_file.filename.split('.')

    # Filter incorrect type of file
    ALLOWED_EXTENSIONS = ['png', 'jpg', 'jpeg', 'JPG', 'PNG', 'JPEG']
    if extn not in ALLOWED_EXTENSIONS:
        return 'Incorrect file type'
    localtime = now.strftime('%H%M%S')
    filename = name + localtime
    path = os.path.join("app", "static", username)
    mkdir(path)
    path_origin = os.path.join(path, filename+'.'+ extn)

    fname = os.path.join(path, filename + '.' + extn)
    print(fname)

    new_file.save(fname)

    # Filter unreasonable big file
    fsize = os.path.getsize(fname)
    fsize = fsize / float(1024 * 1024)
    if fsize > 100:
        return 'Unexpected big file'

    # generate and save the thumbnail
    im = Image.open(fname)
    im.thumbnail((200,100))
    path_tn = os.path.join(path, filename+'_tn'+'.'+ extn)
    im.save(path_tn)

    # generate and save the result of text detection
    # construct the argument parser and parse the arguments
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--image", type=str,
                    help="path to input image")
    ap.add_argument("-east", "--east", type=str,
                    help="path to input EAST text detector")
    ap.add_argument("-c", "--min-confidence", type=float, default=0.5,
                    help="minimum probability required to inspect a region")
    ap.add_argument("-w", "--width", type=int, default=320,
                    help="resized image width (should be multiple of 32)")
    ap.add_argument("-e", "--height", type=int, default=320,
                    help="resized image height (should be multiple of 32)")
    args = vars(ap.parse_args())

    # load the input image and grab the image dimensions
    image = cv2.imread(fname)
    orig = image.copy()
    (H, W) = image.shape[:2]

    # set the new width and height and then determine the ratio in change
    # for both the width and height
    (newW, newH) = (args["width"], args["height"])
    rW = W / float(newW)
    rH = H / float(newH)

    # resize the image and grab the new image dimensions
    image = cv2.resize(image, (newW, newH))
    (H, W) = image.shape[:2]

    # define the two output layer names for the EAST detector model that
    # we are interested -- the first is the output probabilities and the
    # second can be used to derive the bounding box coordinates of text
    layerNames = [
        "feature_fusion/Conv_7/Sigmoid",
        "feature_fusion/concat_3"]

    # load the pre-trained EAST text detector
    # print("[INFO] loading EAST text detector...")
    net = cv2.dnn.readNet("app/frozen_east_text_detection.pb")

    # construct a blob from the image and then perform a forward pass of
    # the model to obtain the two output layer sets
    blob = cv2.dnn.blobFromImage(image, 1.0, (W, H),
                                 (123.68, 116.78, 103.94), swapRB=True, crop=False)
    start = time.time()
    net.setInput(blob)
    (scores, geometry) = net.forward(layerNames)
    end = time.time()

    # show timing information on text prediction
    # print("[INFO] text detection took {:.6f} seconds".format(end - start))

    # grab the number of rows and columns from the scores volume, then
    # initialize our set of bounding box rectangles and corresponding
    # confidence scores
    (numRows, numCols) = scores.shape[2:4]
    rects = []
    confidences = []

    # loop over the number of rows
    for y in range(0, numRows):
        # extract the scores (probabilities), followed by the geometrical
        # data used to derive potential bounding box coordinates that
        # surround text
        scoresData = scores[0, 0, y]
        xData0 = geometry[0, 0, y]
        xData1 = geometry[0, 1, y]
        xData2 = geometry[0, 2, y]
        xData3 = geometry[0, 3, y]
        anglesData = geometry[0, 4, y]

        # loop over the number of columns
        for x in range(0, numCols):
            # if our score does not have sufficient probability, ignore it
            if scoresData[x] < args["min_confidence"]:
                continue

            # compute the offset factor as our resulting feature maps will
            # be 4x smaller than the input image
            (offsetX, offsetY) = (x * 4.0, y * 4.0)

            # extract the rotation angle for the prediction and then
            # compute the sin and cosine
            angle = anglesData[x]
            cos = np.cos(angle)
            sin = np.sin(angle)

            # use the geometry volume to derive the width and height of
            # the bounding box
            h = xData0[x] + xData2[x]
            w = xData1[x] + xData3[x]

            # compute both the starting and ending (x, y)-coordinates for
            # the text prediction bounding box
            endX = int(offsetX + (cos * xData1[x]) + (sin * xData2[x]))
            endY = int(offsetY - (sin * xData1[x]) + (cos * xData2[x]))
            startX = int(endX - w)
            startY = int(endY - h)

            # add the bounding box coordinates and probability score to
            # our respective lists
            rects.append((startX, startY, endX, endY))
            confidences.append(scoresData[x])

    # apply non-maxima suppression to suppress weak, overlapping bounding
    # boxes
    boxes = non_max_suppression(np.array(rects), probs=confidences)

    # loop over the bounding boxes
    for (startX, startY, endX, endY) in boxes:
        # scale the bounding box coordinates based on the respective
        # ratios
        startX = int(startX * rW)
        startY = int(startY * rH)
        endX = int(endX * rW)
        endY = int(endY * rH)

        # draw the bounding box on the image
        cv2.rectangle(orig, (startX, startY), (endX, endY), (0, 255, 0), 2)

    # show the output image
    # cv2.imshow("Text Detection", orig)
    # cv2.waitKey(0)
    # save the new image in a new path
    path_td = os.path.join(path, filename + '_td' + '.' + extn);
    cv2.imwrite(path_td, orig)

    object = open(path_origin, 'rb')
    s3.Bucket('a2homework').put_object(Key=path_origin, Body=object)
    object2 = open(path_tn, 'rb')
    s3.Bucket('a2homework').put_object(Key=path_tn, Body=object2)
    object3 = open(path_td, 'rb')
    s3.Bucket('a2homework').put_object(Key=path_td, Body=object3)

    os.remove(path_origin)
    os.remove(path_tn)
    os.remove(path_td)

    path_s3 = 's3://a2homework/'

    cnx = get_db()
    cursor = cnx.cursor()

    query = '''SELECT user_id FROM user_information WHERE username = %s'''
    cursor.execute(query, (username,))
    user_id = cursor.fetchall()
    print(user_id)
    if len(user_id) == 1:
        user_id = user_id[0][0]

    query = '''INSERT INTO image VALUES (%s,%s,%s,%s)'''
    cursor.execute(query, (user_id, path_s3 + path_origin, path_s3 + path_tn, path_s3 + path_td))
    cnx.commit()

    return 'Upload file success'
