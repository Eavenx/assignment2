from flask import Flask
from flask_sqlalchemy import SQLAlchemy

webapp = Flask(__name__)
webapp.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://admin:12345678@alldata.c3fcxrbhjwar.us-east-1.rds.amazonaws.com/mydb?charset=utf8'
webapp.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(webapp)

from app import main
from app import user_op
from app import user_op_data
from app import view
from app import suppression
from app import upload



