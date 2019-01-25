from flask_restplus import Resource, reqparse, Namespace, fields
from resources._logger import *
from queries.cql_queries import *
from schemas.gwas_info_node_schema import GwasInfoNodeSchema
from schemas.user_node_schema import UserNodeSchema
from schemas.added_by_rel_schema import AddedByRelSchema
from queries.user_node import User
from queries.gwas_info_node import GwasInfo
from queries.added_by_rel import AddedByRel
import time
import marshmallow.exceptions
from werkzeug.exceptions import BadRequest

api = Namespace('gwasinfo', description="Get information about available GWAS summary datasets")

parser1 = api.parser()
parser1.add_argument(
    'X-Api-Token', location='headers', required=False, default='null',
    help='Public datasets can be queried without any authentication, but some studies are only accessible by specific users. To authenticate we use Google OAuth2.0 access tokens. The easiest way to obtain an access token is through the [TwoSampleMR R](https://mrcieu.github.io/TwoSampleMR/#authentication) package using the `get_mrbase_access_token()` function.')


@api.route('/list')
@api.expect(parser1)
@api.doc(description="Return all available GWAS summary datasets")
class GwasList(Resource):
    def get(self):
        logger_info()
        user_email = get_user_email(request.headers.get('X-Api-Token'))
        return get_all_gwas(user_email)


@api.route('/<id>')
@api.expect(parser1)
@api.doc(
    description="Get information about specified GWAS summary datasets",
    params={'id': 'An ID or comma-separated list of IDs'}
)
class GwasInfoGet(Resource):
    def get(self, id):
        logger_info()
        user_email = get_user_email(request.headers.get('X-Api-Token'))
        study_ids = id.replace(';', '').split(',')
        recs = []

        for sid in study_ids:
            try:
                recs.append(get_specific_gwas(user_email, sid))
            except LookupError as e:
                continue

        return recs


parser2 = reqparse.RequestParser()
parser2.add_argument('id', required=True, type=str, action='append', default=[], help="List of IDs")
parser2.add_argument(
    'X-Api-Token', location='headers', required=False, default='null',
    help='Public datasets can be queried without any authentication, but some studies are only accessible by specific users. To authenticate we use Google OAuth2.0 access tokens. The easiest way to obtain an access token is through the [TwoSampleMR R](https://mrcieu.github.io/TwoSampleMR/#authentication) package using the `get_mrbase_access_token()` function.')


@api.route('/', methods=["post"])
@api.doc(
    description="Get information about specified GWAS summary datasets")
class GwasInfoPost(Resource):
    @api.expect(parser2)
    def post(self):
        logger_info()
        args = parser2.parse_args()
        user_email = get_user_email(request.headers.get('X-Api-Token'))

        if (len(args['id']) == 0):
            # TODO @Gib reqparse will not allow no args provided shall we remove?
            return get_all_gwas(user_email)
        else:
            recs = []
            for sid in args['id']:
                try:
                    recs.append(get_specific_gwas(user_email, sid))
                except LookupError as e:
                    continue
            return recs


parser3 = api.parser()
parser3.add_argument(
    'X-Api-Token', location='headers', required=True,
    help='You must be authenticated to submit new GWAS data. To authenticate we use Google OAuth2.0 access tokens. The easiest way to obtain an access token is through the [TwoSampleMR R](https://mrcieu.github.io/TwoSampleMR/#authentication) package using the `get_mrbase_access_token()` function.')

params = GwasInfoNodeSchema.get_flask_model()
params['comments'] = fields.String
model = api.model('study', params)


@api.route('/add')
@api.expect(parser3)
@api.doc(description="Add new gwas information")
class StudyResource(Resource):
    study_schema = GwasInfoNodeSchema()
    user_schema = UserNodeSchema()
    added_rel = AddedByRelSchema()

    @api.expect(model, validate=False)
    def post(self):
        logger_info()

        try:
            req = request.get_json()

            # load
            user = User(self.user_schema.load({"uid": get_user_email(request.headers.get('X-Api-Token'))}))
            study = GwasInfo(self.study_schema.load(req))

            try:
                props = self.added_rel.load({'epoch': time.time(), "comments": req['comments']})
            except KeyError:
                props = self.added_rel.load({'epoch': time.time()})

            # persist or update
            user.create_node()
            study.create_node()

            # link study to user; record epoch and optional comments
            rel = AddedByRel(**props)
            rel.create_rel(study, user)

        except marshmallow.exceptions.ValidationError as e:
            raise BadRequest("Could not validate payload: {}".format(e))
