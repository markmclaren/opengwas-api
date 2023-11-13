from marshmallow import fields, validate, post_load
from schemas.frpm_schema import FRPMSchema


class UserNodeSchema(FRPMSchema):
    uid = fields.Str(required=False, validate=validate.Email(error='Not a valid email address'),
                     description="Email address of user.")
    admin = fields.Bool(required=False, description="Is the user an admin?")
    jwt_timestamp = fields.Int(required=False, description="JWT timestamp")
    first_name = fields.Str(required=True, allow_none=False, description="First name")
    last_name = fields.Str(required=True, allow_none=False, description="Last name")

    @post_load
    def lower_strip_email(self, item):
        item['uid'] = item['uid'].lower().strip()
        return item
