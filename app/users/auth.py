from flask import Blueprint, url_for, request, redirect, flash,session
from cryptography.fernet import Fernet
import time
import json
import datetime

from middleware import limiter, Validator
from queries.cql_queries import *
from resources import microsoft, github, GitHubUniversities
from resources.email import Email
from resources.globals import Globals
from .login_manager import *
from . import organisations


users_auth_bp = Blueprint('auth', __name__)


@users_auth_bp.route('/providers/init')
def init_providers():
    return {
        'microsoft': microsoft.generate_signin_link(url_for('users.auth.signin_via_microsoft', _external=True))['auth_uri'],
        'github': Globals.GH_APPS_AUTH_URL + '?client_id=' + Globals.GH_APPS_AUTH_CLIENT_ID + '&redirect_uri=' + url_for('users.auth.signin_via_github', _external=True),
        'github_emails': session.get('github_emails')
    }


@users_auth_bp.route('/microsoft/redirect')
def signin_via_microsoft():
    try:
        microsoft.get_tokens(request.args)
    except Exception as e:
        flash(str(e), 'danger')
        return redirect(url_for('/'))

    user = _add_user_from_microsoft()
    signin_user(user)

    return redirect(url_for('users.index.index'))


def _add_user_from_microsoft():
    try:  # Parse Microsoft Graph API responses
        user_org_info = microsoft.get_user_and_org_info()
    except Exception as e:
        flash(str(e), 'danger')
        return redirect(url_for('/'))

    try:
        domain = user_org_info['user']['mail'].split("@")[1]
        if user_org_info['type'] == 'ORG':
            # Create/merge Org node
            org = organisations.get_or_add_org(provider='MS', domain=domain, new_org=user_org_info['organization'])
            # Create/merge User node as well as MEMBER_OF and MEMBER_OF_ORG relationships
            user = add_new_user(email=user_org_info['user']['mail'],
                         first_name=user_org_info['user']['givenName'], last_name=user_org_info['user']['surname'],
                         tier='ORG', org_uuid=org['uuid'], user_org_info=user_org_info['user_org'])

        else:
            # Just create/merge User node
            user = add_new_user(email=user_org_info['user']['mail'],
                         first_name=user_org_info['user']['givenName'], last_name=user_org_info['user']['surname'],
                         tier='PER')
    except Exception as e:
        flash(str(e), 'danger')
        return redirect(url_for('/'))

    return user.data()['u']


@users_auth_bp.route('/github/redirect')
def signin_via_github():
    try:
        github.request_tokens(request.args)
    except Exception as e:
        flash("Cannot retrieve your information from GitHub. " + str(e), 'danger')
        return redirect(url_for('/'))

    gh_emails = _search_user_by_github()
    if 'existing' in gh_emails:
        signin_user({'uid': gh_emails['existing'][0]})
        return redirect(url_for('users.index.index'))
    else:
        session['github_emails'] = gh_emails['new']
        return redirect(url_for('/'))


def _search_user_by_github():
    try:
        gh_emails = github.get_user_emails()
    except Exception as e:
        flash("Error in parsing email addresses from GitHub. " + str(e), 'danger')
        return redirect(url_for('/'))

    og_users = get_user_by_emails(gh_emails)
    for u in og_users:
        if u['uid'] in gh_emails:  # Found existing user
            return {'existing': [u['uid']]}

    return {'new': gh_emails}


@users_auth_bp.route('/github/cancel')
def cancel_signin_via_github():
    session.pop('github_emails', None)
    return redirect(url_for('/'))


@users_auth_bp.route('/github/signup')
def signup_via_github():
    req = request.args.to_dict()

    try:
        _check_github_email(req['email'])
    except Exception as e:
        return {'message': str(e)}, 400

    session.pop('github_emails', None)

    try:
        Validator('UserNodeSchema', partial=True).validate({
            'uid': req["email"], 'first_name': req['first_name'], 'last_name': req['last_name']
        })
    except Exception as e:
        return {'message': "Please provide valid email address, first name and last name."}, 400

    user = get_user_by_email(req['email'])
    if user is None:
        return signup_via_email(req["email"], req['first_name'], req['last_name'], False)

    signin_user(user.data()['u'])

    return {
        'message': "Signing in existing user.",
        'redirect': url_for('users.index.index', _external=True)
    }


def _check_github_email(email):
    if not session.get('github_emails') or email not in session['github_emails']:
        raise Exception("Please provide an email address that is verified in your GitHub account.")


@users_auth_bp.route('/email/check')
@limiter.limit('30 per day')  # Max number of requests per IP
def check_email_and_names():
    req = request.args.to_dict()
    try:
        Validator('UserNodeSchema', partial=True).validate({'uid': req['email']})
    except Exception as e:
        return {'message': "Please provide a valid email address."}, 400

    # For existing user, send one-time sign-in link
    user = get_user_by_email(req['email'])
    if user:
        return send_email(req['email'])

    try:
        domain = req['email'].split("@")[1]
        if not GitHubUniversities().search_by_domain(domain):
            raise Exception("Only new user with an academic email address can sign up via this method. If you only have non-academic email address, please first use the Microsoft or GitHub channel to sign up (i.e. sign in for the first time). You will then be able to sign in using email.")
    except Exception as e:
        return {'message': str(e)}, 400

    # For new user, check names and send one-time sign-in link containing names
    try:
        Validator('UserNodeSchema', partial=True).validate({
            'uid': req["email"], 'first_name': req['first_name'], 'last_name': req['last_name']
        })
    except Exception as e:
        return {'message': "Please provide valid first name and last name."}, 400

    return send_email(req['email'], req['first_name'], req['last_name'])


@limiter.limit('15 per day')  # Max number of requests per IP
def send_email(email, first_name=None, last_name=None):
    link, expiry = _generate_email_signin_link(email, first_name, last_name)
    expiry_str = datetime.datetime.strftime(datetime.datetime.fromtimestamp(expiry).astimezone(), '%Y-%m-%d %H:%M:%S %Z')

    @limiter.limit('3 per day', key_func=lambda: email)  # Max number of requests per IP per recipient email address
    def __send():
        return Email().send_signin_email(link, email, expiry_str)

    try:
        result = __send()
    except Exception as e:
        return {
            'message': "Failed to send email. Please try again later or contact us. Details: " + str(e)
        }, 500
    return result


def _generate_email_signin_link(email, first_name=None, last_name=None):
    fernet = Fernet(Globals.app_config['fernet']['key'])
    expiry = int(time.time()) + Globals.EMAIL_VERIFICATION_LINK_VALIDITY
    message = fernet.encrypt(json.dumps({
        'email': email,
        'first_name': first_name,
        'last_name': last_name,
        'expiry': expiry
    }).encode())
    link = url_for('users.auth.signin_via_email', _external=True, message=message.decode())
    return link, expiry


@users_auth_bp.route('/email/signin')
def signin_via_email():
    req = request.args.to_dict()
    try:
        email, first_name, last_name = _decrypt_email_link(req["message"])
    except Exception as e:
        flash(str(e), 'danger')
        return redirect(url_for('/'))

    user = get_user_by_email(email)
    if user is None:
        return signup_via_email(email, first_name, last_name)

    signin_user(user.data()['u'])

    return redirect(url_for('users.index.index'))


def _decrypt_email_link(message):
    fernet = Fernet(Globals.app_config['fernet']['key'])
    try:
        message = json.loads(fernet.decrypt(message.encode()).decode())
        email = message['email']
        first_name = message['first_name']
        last_name = message['last_name']
        expiry = message['expiry']
    except Exception as e:
        raise Exception("Invalid sign in link. Please get a new one.")

    if int(time.time()) > expiry:
        raise Exception("Sign in link expired. Please get a new one.")

    return email, first_name, last_name


@users_auth_bp.route('/email/signup')
def signup_via_email(email, first_name, last_name, return_redirect=True):
    try:
        Validator('UserNodeSchema', partial=True).validate({
            'uid': email, 'first_name': first_name, 'last_name': last_name
        })
    except Exception as e:
        return {'message': "Please provide valid first name and last name."}, 400

    try:
        user = _add_user_from_email(email, first_name, last_name, return_redirect=False)
        signin_user(user)
    except Exception as e:
        return {'message': str(e)}, 400

    if return_redirect:
        return redirect(url_for('users.index.index'))
    return {
        'message': "Welcome - please wait to be redirected.",
        'redirect': url_for('users.index.index', _external=True)
    }


def _add_user_from_email(email, first_name, last_name, return_redirect=True):
    try:
        domain = email.split("@")[1]
        org = organisations.get_or_add_org(provider='GH', domain=domain, new_org=GitHubUniversities().search_by_domain(domain))
        if org:
            user = add_new_user(email=email, first_name=first_name, last_name=last_name, tier='ORG', org_uuid=org['uuid'])
        else:
            user = add_new_user(email=email, first_name=first_name, last_name=last_name, tier='PER')
    except Exception as e:
        if return_redirect:
            flash(str(e), 'danger')
            return redirect(url_for('/'))
        else:
            raise e

    return user.data()['u']


@users_auth_bp.route('/signout')
def signout():
    sign_out_user()
    flash('You have signed out successfully. Please note your API token (if any) is still valid.')
    return redirect(url_for('/'))
