from flask_restplus import Resource, Namespace
from queries.cql_queries import *
from schemas.gwas_info_node_schema import GwasInfoNodeSchema
from queries.gwas_info_node import GwasInfo
from werkzeug.datastructures import FileStorage
import marshmallow.exceptions
from werkzeug.exceptions import BadRequest
from resources.globals import Globals
import hashlib
import gzip
from schemas.gwas_row_schema import GwasRowSchema
import json
import shutil
from resources.auth import get_user_email
from flask import request
from schemas.gwas_info_node_schema import valid_genome_build
from schemas.group_node_schema import valid_group_names
import requests
import logging

logger = logging.getLogger('debug-log')

api = Namespace('edit', description="Upload and delete data")


@api.route('/add')
@api.doc(description="Add new gwas metadata")
class Add(Resource):
    parser = api.parser()
    parser.add_argument(
        'X-Api-Token', location='headers', required=True,
        help='You must be authenticated to submit new GWAS data. To authenticate we use Google OAuth2.0 access tokens. The easiest way to obtain an access token is through the [TwoSampleMR R](https://mrcieu.github.io/TwoSampleMR/#authentication) package using the `get_mrbase_access_token()` function.')
    parser.add_argument('group_name', type=str, required=True,
                        help='Name for the group this study should belong to.', choices=tuple(valid_group_names))
    parser.add_argument('build', type=str, choices=tuple(valid_genome_build), required=True,
                        help='Name for the group this study should belong to.')
    GwasInfoNodeSchema.populate_parser(parser,
                                       ignore={GwasInfo.get_uid_key(), 'build', 'filename', 'path', 'md5', 'priority',
                                               'mr'})

    @api.expect(parser)
    def post(self):

        try:
            req = self.parser.parse_args()
            user_uid = get_user_email(request.headers.get('X-Api-Token'))
            group_name = req['group_name']

            req.pop('X-Api-Token')
            req.pop('group_name')

            gwas_uid = add_new_gwas(user_uid, req, {group_name})

            return {"id": gwas_uid}, 200

        except marshmallow.exceptions.ValidationError as e:
            raise BadRequest("Could not validate payload: {}".format(e))


@api.route('/delete')
@api.doc(description="Delete gwas metadata")
class Delete(Resource):
    parser = api.parser()
    parser.add_argument(
        'X-Api-Token', location='headers', required=True,
        help='You must be authenticated to delete GWAS data. To authenticate we use Google OAuth2.0 access tokens. The easiest way to obtain an access token is through the [TwoSampleMR R](https://mrcieu.github.io/TwoSampleMR/#authentication) package using the `get_mrbase_access_token()` function.')
    parser.add_argument('id', type=str, required=True, help="Identifier to which the summary stats belong.")

    @api.expect(parser)
    def delete(self):
        args = self.parser.parse_args()
        user_uid = get_user_email(request.headers.get('X-Api-Token'))

        try:
            check_user_is_admin(user_uid)
        except PermissionError as e:
            return {"message": str(e)}, 403

        delete_gwas(user_uid)

        return {"message": "successfully deleted."}, 200


@api.route('/upload')
@api.doc(description="Upload GWAS summary stats file to MR Base")
class Upload(Resource):
    parser = api.parser()
    parser.add_argument(
        'X-Api-Token', location='headers', required=True,
        help='You must be authenticated to submit new GWAS data. To authenticate we use Google OAuth2.0 access tokens. The easiest way to obtain an access token is through the [TwoSampleMR R](https://mrcieu.github.io/TwoSampleMR/#authentication) package using the `get_mrbase_access_token()` function.')
    parser.add_argument('chr_col', type=int, required=True, help="Column index for chromosome")
    parser.add_argument('pos_col', type=int, required=True, help="Column index for base position")
    parser.add_argument('ea_col', type=int, required=True, help="Column index for effect allele")
    parser.add_argument('oa_col', type=int, required=True, help="Column index for non-effect allele")
    parser.add_argument('beta_col', type=int, required=True, help="Column index for effect size")
    parser.add_argument('se_col', type=int, required=True, help="Column index for standard error")
    parser.add_argument('pval_col', type=int, required=True, help="Column index for P-value")
    parser.add_argument('delimiter', type=str, required=True, choices=("comma", "tab"),
                        help="Column delimiter for file")
    parser.add_argument('header', type=str, required=True, help="Does the file have a header line?",
                        choices=('True', 'False'))
    parser.add_argument('ncase_col', type=int, required=False, help="Column index for case sample size")
    parser.add_argument('snp_col', type=int, required=False, help="Column index for dbsnp rs-identifer")
    parser.add_argument('eaf_col', type=int, required=False,
                        help="Column index for effect allele frequency")
    parser.add_argument('oaf_col', type=int, required=False,
                        help="Column index for other allele frequency")
    parser.add_argument('imp_z_col', type=int, required=False,
                        help="Column number for summary statistics imputation Z score")
    parser.add_argument('imp_info_col', type=int, required=False,
                        help="Column number for summary statistics imputation INFO score")
    parser.add_argument('ncontrol_col', type=int, required=False,
                        help="Column index for control sample size; total sample size if continuous trait")
    parser.add_argument('id', type=str, required=True,
                        help="Identifier to which the summary stats belong.")
    parser.add_argument('gwas_file', location='files', type=FileStorage, required=True,
                        help="Path to GWAS summary stats text file for upload.")
    parser.add_argument('gzipped', type=str, required=True, help="Is the file compressed with gzip?",
                        choices=('True', 'False'))

    @staticmethod
    def read_gzip(p, sep, args):
        with gzip.open(p, 'rt', encoding='utf-8') as f:
            if args['header'] == 'True':
                f.readline()

            for line in f:
                Upload.validate_row_with_schema(line.strip().split(sep), args)

    @staticmethod
    def read_plain_text(p, sep, args):
        with open(p, 'r') as f:
            if args['header'] == 'True':
                f.readline()

            for line in f:
                Upload.validate_row_with_schema(line.strip().split(sep), args)

    @staticmethod
    def md5(fname):
        hash_md5 = hashlib.md5()
        with open(fname, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    @staticmethod
    def validate_row_with_schema(line_split, args):
        row = dict()

        if 'chr_col' in args and args['chr_col'] is not None:
            row['chr'] = line_split[args['chr_col']]
        if 'pos_col' in args and args['pos_col'] is not None:
            row['pos'] = line_split[args['pos_col']]
        if 'ea_col' in args and args['ea_col'] is not None:
            row['ea'] = line_split[args['ea_col']]
        if 'oa_col' in args and args['oa_col'] is not None:
            row['oa'] = line_split[args['oa_col']]
        if 'eaf_col' in args and args['eaf_col'] is not None:
            row['eaf'] = line_split[args['eaf_col']]
        if 'beta_col' in args and args['beta_col'] is not None:
            row['beta'] = line_split[args['beta_col']]
        if 'se_col' in args and args['se_col'] is not None:
            row['se'] = line_split[args['se_col']]
        if 'pval_col' in args and args['pval_col'] is not None:
            row['pval'] = line_split[args['pval_col']]
        if 'ncontrol_col' in args and args['ncontrol_col'] is not None:
            row['ncontrol'] = line_split[args['ncontrol_col']]
        if 'ncase_col' in args and args['ncase_col'] is not None:
            row['ncase'] = line_split[args['ncase_col']]

        # check row - raises validation exception if invalid
        schema = GwasRowSchema()
        schema.load(row)

    @staticmethod
    def __convert_index(val):
        try:
            return val - 1
        except TypeError:
            return val

    @api.expect(parser)
    def post(self):
        args = self.parser.parse_args()

        # convert to 0-based indexing
        args['chr_col'] = Upload.__convert_index(args['chr_col'])
        args['pos_col'] = Upload.__convert_index(args['pos_col'])
        args['ea_col'] = Upload.__convert_index(args['ea_col'])
        args['oa_col'] = Upload.__convert_index(args['oa_col'])
        args['beta_col'] = Upload.__convert_index(args['beta_col'])
        args['se_col'] = Upload.__convert_index(args['se_col'])
        args['pval_col'] = Upload.__convert_index(args['pval_col'])
        args['ncase_col'] = Upload.__convert_index(args['ncase_col'])
        args['snp_col'] = Upload.__convert_index(args['snp_col'])
        args['eaf_col'] = Upload.__convert_index(args['eaf_col'])
        args['imp_z_col'] = Upload.__convert_index(args['imp_z_col'])
        args['imp_info_col'] = Upload.__convert_index(args['imp_info_col'])
        args['ncontrol_col'] = Upload.__convert_index(args['ncontrol_col'])

        study_folder = os.path.join(Globals.UPLOAD_FOLDER, args['id'])
        raw_folder = os.path.join(study_folder, 'raw')

        # make folder for new dataset
        if not os.path.exists(study_folder):
            os.makedirs(study_folder)

        if not os.path.exists(raw_folder):
            os.makedirs(raw_folder)

        if args['gzipped'] == 'True':
            output_path = os.path.join(raw_folder, 'upload.txt.gz')
        else:
            output_path = os.path.join(raw_folder, 'upload.txt')

        # save file to server
        args['gwas_file'].save(output_path)

        # compress file
        if args['gzipped'] != 'True':
            with open(output_path, 'rb') as f_in:
                with gzip.open(output_path + '.gz', 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            os.remove(output_path)
            output_path += '.gz'

        # fix delim
        if args['delimiter'] == "comma":
            args['delimiter'] = ","
        elif args['delimiter'] == "tab":
            args['delimiter'] = "\t"

        try:
            Upload.read_gzip(output_path, args['delimiter'], args)
        except OSError:
            return {'message': 'Could not read file. Check encoding'}, 400
        except marshmallow.exceptions.ValidationError as e:
            return {'message': 'The file format was invalid {}'.format(e)}, 400
        except IndexError as e:
            return {'message': 'Check column numbers and separator: {}'.format(e)}, 400

        # update the graph
        update_filename_and_path(str(args['id']), output_path, Upload.md5(output_path))

        # write to json
        j = dict()
        for k in args:
            if args[k] is not None and k != 'gwas_file' and k != 'X-Api-Token' and k != 'gzipped':
                j[k] = args[k]

        # get build
        g = GwasInfo.get_node(j['id'])
        j['build'] = g['build']

        # convert text to bool
        if j['header'] == "True":
            j['header'] = True
        else:
            j['header'] = False

        with open(os.path.join(raw_folder, 'upload.json'), 'w') as f:
            json.dump(j, f)

        with open(os.path.join(raw_folder, 'wdl.json'), 'w') as f:
            json.dump({"upload.StudyId": str(args['id'])}, f)

        # add to cromwell queue
        r = requests.post(Globals.CROMWELL_URL + "/api/workflows/v1",
                          files={'workflowSource': open(Globals.WDL_PATH, 'rb'),
                                 'workflowInputs': open(os.path.join(raw_folder, 'wdl.json'), 'rb')})
        assert r.status_code == 201
        assert r.json()['status'] == "Submitted"
        logger.info("Submitted {} to cromwell".format(r.json()['id']))

        return {'message': 'Upload successful. Cromwell id :{}'.format(r.json()['id'])}, 201
