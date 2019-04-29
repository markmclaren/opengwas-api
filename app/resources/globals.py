from elasticsearch import Elasticsearch
import json
import platform
import os
from neo4j import GraphDatabase
import logging


class Globals:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    VERSION = '2.0.0'

    root_path = os.path.dirname(os.path.dirname(__file__))

    # Toggle for local vs deployed
    APP_CONF = os.path.join(root_path, 'conf_files', 'app_conf.json')
    PLINK = os.path.join(root_path, 'bin', 'plink' + '_' + platform.system())
    LD_REF = os.path.join(root_path, 'ld_files', 'data_maf0.01_rs')
    TMP_FOLDER = os.path.join(root_path, 'tmp')
    UPLOAD_FOLDER = os.path.join(os.sep, 'data', 'bgc')
    LOG_FILE = os.path.join(root_path, 'logs', 'mrbaseapi.log')
    LOG_FILE_DEBUG = os.path.join(root_path, 'logs', 'mrbaseapi-debug.log')

    OAUTH2_URL = 'https://www.googleapis.com/oauth2/v1/tokeninfo?access_token='
    USERINFO_URL = 'https://www.googleapis.com/oauth2/v1/userinfo?alt=json&access_token='

    """ Set environment files to toggle between local and production & private vs public APIs """
    with open(APP_CONF) as f:
        app_config = json.load(f)

        try:
            if os.environ['ENV'] == 'production':
                app_config = app_config['production']
            else:
                app_config = app_config['local']
        except KeyError as e:
            app_config = app_config['local']
            logging.warning("Environmental variable 'ENV' not set assuming local configuration")

        try:
            if os.environ['ACCESS'] == 'public':
                app_config['access'] = 'public'
            else:
                app_config['access'] = 'private'
        except KeyError as e:
            app_config['access'] = 'private'
            logging.warning("Environmental variable 'ACCESS' not set assuming private configuration")

    dbConnection = GraphDatabase.driver(
        'bolt://' + app_config['neo4j']['host'] + ":" + str(app_config['neo4j']['port']),
        auth=(app_config['neo4j']['user'], app_config['neo4j']['passwd'])
    )

    # connect to elasticsearch
    es = Elasticsearch(
        [{'host': app_config['es']['host'], 'port': app_config['es']['port']}]
    )

    mrb_batch = 'MRB'
    study_batches = [mrb_batch, 'UKB-a', 'UKB-b', 'UKB-c', 'pQTL-a', 'eqtl-a']
