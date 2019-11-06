from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os


webapp = Flask(__name__)
webapp.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://admin:12345678@alldata.c3fcxrbhjwar.us-east-1.rds.amazonaws.com/mydb?charset=utf8'
webapp.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(webapp)

webapp.config['SECRET_KEY'] = os.urandom(24)
from app import main
from app import elb_op
from app import config
