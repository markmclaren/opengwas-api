from flask import Flask
import os
import time
import sys
sys.path.append('..')

from queries.cql_queries import set_user_jwt_timestamp
from resources.globals import Globals
from resources.jwt import generate_jwt


def get_jwt():
    try:
        return os.environ['MRB_TOKEN']
    except Exception:
        with Flask(__name__).app_context():
            timestamp = int(time.time())
            jwt = generate_jwt(Globals.app_config['test']['uid'], timestamp)
            set_user_jwt_timestamp(Globals.app_config['test']['uid'], timestamp)
            return jwt
