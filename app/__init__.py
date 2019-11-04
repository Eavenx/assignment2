
from flask import Flask
import os

webapp = Flask(__name__)

webapp.config['SECRET_KEY'] = os.urandom(24)

from app import manager_main
from app import s3_examples


from app import main
from app import elb_op
from app import config