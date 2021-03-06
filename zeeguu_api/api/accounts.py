import flask
import sqlalchemy
import zeeguu_core
from flask import request
from zeeguu_core.model import User, Cohort, Teacher
from zeeguu_core.model.unique_code import UniqueCode
from zeeguu_api.api.sessions import get_session, get_anon_session
from zeeguu_api.api.utils.abort_handling import make_error
from zeeguu_api.emailer.user_activity import send_new_user_account_email
from zeeguu_api.emailer.password_reset import send_password_reset_email

from .utils.route_wrappers import cross_domain
from . import api, db_session


def _valid_invite_code(invite_code: str):
    return (
            invite_code in zeeguu_core.app.config.get("INVITATION_CODES")
            or Cohort.exists_with_invite_code(invite_code)
    )


@api.route("/add_user/<email>", methods=["POST"])
@cross_domain
def add_user(email):
    """

        Creates user, then redirects to the get_session
        endpoint. Returns a session

    """

    password = request.form.get("password")
    username = request.form.get("username")
    invite_code = request.form.get("invite_code")
    cohort_name = ''

    if password is None or len(password) < 4:
        return make_error(400, "Password should be at least 4 characters long")

    if not (_valid_invite_code(invite_code)):
        return make_error(400, "Invitation code is not recognized. Please contact us.")

    try:

        cohort = Cohort.query.filter_by(inv_code=invite_code).first()

        if cohort:
            # if the invite code is from a cohort, then there has to be capacity
            if not cohort.cohort_still_has_capacity():
                return make_error(400, "No more places in this class. Please contact us.")

            cohort_name = cohort.name

        new_user = User(email, username, password, invitation_code=invite_code, cohort=cohort)
        db_session.add(new_user)

        if cohort:
            if cohort.is_cohort_of_teachers:
                teacher = Teacher(new_user)
                db_session.add(teacher)

        db_session.commit()

        send_new_user_account_email(username, invite_code, cohort_name)


    except sqlalchemy.exc.IntegrityError:
        return make_error(401, "There is already an account for this email.")
    except ValueError:
        return make_error(400, "Invalid value")

    return get_session(email)


@api.route("/add_anon_user", methods=["POST"])
@cross_domain
def add_anon_user():
    """

        Creates anonymous user, then redirects to the get_session
        endpoint. Returns a session

    """

    # These two are post parameters required by the method
    uuid = request.form.get("uuid", None)
    password = request.form.get("password", None)

    # These two are optional
    language_code = request.form.get("learned_language_code", None)
    native_code = request.form.get("native_language_code", None)

    try:
        new_user = User.create_anonymous(uuid, password, language_code, native_code)
        db_session.add(new_user)
        db_session.commit()
    except ValueError as e:
        flask.abort(flask.make_response("Could not create anon user.", 400))
    except sqlalchemy.exc.IntegrityError as e:
        flask.abort(flask.make_response("Could not create anon user. Maybe uuid already exists?", 400))
    return get_anon_session(uuid)


@api.route("/send_code/<email>", methods=["POST"])
@cross_domain
def send_code(email):
    """
    This endpoint generates a unique code that will be used to allow
    the user to change his/her password. The unique code is send to
    the specified email address.
    """
    code = UniqueCode(email)
    db_session.add(code)
    db_session.commit()

    send_password_reset_email(email, code)

    return "OK"


@api.route("/reset_password/<email>", methods=["POST"])
@cross_domain
def reset_password(email):
    """
    This endpoint can be used to rest a users password.
    To do this a uniquecode is required.
    """
    last_code = UniqueCode.last_code(email)
    code = request.form.get("code", None)
    if not (last_code == code):
        return make_error(400, "Invalid code")

    password = request.form.get("password", None)
    if len(password) < 4:
        return make_error(400, "Password should be at least 4 characters long")

    user = User.find(email)
    if user is None:
        return make_error(400, "Email unknown")
    user.update_password(password)
    db_session.commit()

    # Delete all the codes for this user
    for x in UniqueCode.all_codes_for(email):
        db_session.delete(x)
    db_session.commit()

    return "OK"
