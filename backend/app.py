import os
import uuid
import requests
from datetime import datetime
import base64
import requests
import redis
from dotenv import load_dotenv
from pymongo import MongoClient
from flask import Flask, request, jsonify, session, redirect, url_for, render_template
from flask_session import Session
from flask_cors import CORS
from flask_ckeditor import CKEditor
from flask_ckeditor.utils import cleanify


load_dotenv()  # take environment variables from .env.

app = Flask(__name__)

# App Configuration
app.config["SESSION_TYPE"] = "redis"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_EXPIRES"] = 3600*24*30  # 30 days
app.config["SESSION_USE_SIGNER"] = True
app.config["SESSION_KEY_PREFIX"] = "session:"
app.config["SESSION_COOKIE_NAME"] = "session"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_REDIS"] = redis.from_url(os.getenv("REDIS_URI"))
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

CORS(app, resources={r"/api/*": {"origins": "*"}})

Session(app)

# CKEdito Configuration
app.config["CKEDITOR_PKG_TYPE"] = "full-all"
app.config["CKEDITOR_HEIGHT"] = 400
ckeditor = CKEditor(app)

# Connect to MongoDB
mongodb_client = MongoClient(os.getenv("MONGODB_URI"))["communitycompetitionprod"]

# App context processors
@app.context_processor
def inject_global_vars():
    return dict(
        global_message=mongodb_client.announcements.find_one(
            {"is_active": True}, {"_id": 0}, sort=[("created_at", -1)], limit=1
        ),
        has_global_message=mongodb_client.announcements.count_documents(
            {"is_active": True}
        )
        > 0,
        announcements=list(
            mongodb_client.announcements.find({"is_active": True}, {"_id": 0}).sort(
                "created_at", -1
            )
        ),
    )


@app.context_processor
def format_date():
    def format_date(date):
        return date.strftime("%B %d, %Y")

    return dict(format_date=format_date)


# Frontend endpoints
@app.route("/", methods=["GET"])
def homepage():
    return render_template("home.html")


@app.route("/login", methods=["GET"])
def login():
    if session.get("is_authenticated"):
        return redirect(url_for("homepage"))
    return render_template("login.html")


@app.route("/logout", methods=["GET"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/announcements/<announcement_id>", methods=["GET"])
def announcement(announcement_id):
    announcement = mongodb_client.announcements.find_one(
        {"announcement_id": announcement_id}
    )
    if announcement:
        return render_template("announcement.html", announcement=announcement)
    return redirect(url_for("homepage"))


@app.route("/problems", methods=["GET"])
def problems():
    return render_template(
        "problems.html", all_problems=list(mongodb_client.problems.find())
    )


@app.route("/problems/<problem_id>", methods=["GET"])
def problem(problem_id):
    problem = mongodb_client.problems.find_one({"problem_id": problem_id})
    if problem:
        return render_template("individual-problem.html", problem=problem)
    return redirect(url_for("homepage"))


@app.route("/create-announcement", methods=["GET"])
def create_announcement():
    if (
        session.get("is_authenticated")
        and session["user"]["user_account"]["role"] == "admin"
    ):
        return render_template(
            "create_announcement.html",
            all_announcements=list(mongodb_client.announcements.find({}, {"_id": 0})),
        )
    return redirect(url_for("homepage"))


@app.route("/create-problem", methods=["GET"])
def create_problem():
    if (
        session.get("is_authenticated")
        and session["user"]["user_account"]["role"] == "admin"
    ):
        return render_template("create_problem.html")
    return redirect(url_for("homepage"))


# Maintainance endpoints
@app.route("/api/v1/health", methods=["GET"])
def health():
    return jsonify(
        {"response_code": 200, "message": "OK", "identifier": str(uuid.uuid4())}
    )


# Auth endpoints
@app.route("/api/v1/auth/authenticate", methods=["GET"])
def authenticate():
    if session.get("is_authenticated"):
        return redirect(url_for("homepage"))
    return redirect(
        f"https://login.microsoftonline.com/{os.getenv('TENANT_ID')}/oauth2/v2.0/authorize"
        f"?client_id={os.getenv('CLIENT_ID')}"
        f"&response_type=code"
        f"&redirect_uri={os.getenv('REDIRECT_URI')}"
        f"&response_mode=query"
        f"&scope=openid profile email User.Read"
    )


@app.route("/api/v1/auth/external/_handler", methods=["GET"])
def external_handler():

    if session.get("is_authenticated"):
        return redirect(url_for("homepage"))

    code = request.args.get("code")

    # Exchange authorization code for access token
    token_url = (
        f"https://login.microsoftonline.com/{os.getenv('TENANT_ID')}/oauth2/v2.0/token"
    )
    payload = {
        "client_id": os.getenv("CLIENT_ID"),
        "scope": "openid profile email",
        "code": code,
        "redirect_uri": os.getenv("REDIRECT_URI"),
        "grant_type": "authorization_code",
        "client_secret": os.getenv("CLIENT_SECRET"),
    }

    token_response = requests.post(token_url, data=payload)
    token_data = token_response.json()

    if "access_token" not in token_data:
        return (
            jsonify(
                {
                    "response_code": 400,
                    "message": "Token exchange failed",
                    "identifier": str(uuid.uuid4()),
                }
            ),
            400,
        )

    access_token = token_data["access_token"]

    # Use the access token to call Microsoft Graph API
    user_info_response = requests.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )

    if user_info_response.status_code != 200:
        return (
            jsonify(
                {
                    "response_code": 400,
                    "message": "Failed to get user info",
                    "identifier": str(uuid.uuid4()),
                }
            ),
            400,
        )

    user_info = user_info_response.json()

    user_given_name = user_info.get("givenName", "Unknown")
    primary_email = (
        user_info.get("mail").lower().strip() if "mail" in user_info else None
    )

    if primary_email is None:
        return (
            jsonify(
                {
                    "response_code": 400,
                    "message": "Primary email not found",
                    "identifier": str(uuid.uuid4()),
                }
            ),
            400,
        )

    # MongoDB user query and update
    now = datetime.utcnow()  # Current timestamp for created_at and last_logged_in_at

    # Update user details or insert if not exists
    update_result = mongodb_client.users.update_one(
        {"user_account.primary_email": primary_email},
        {
            "$set": {
                "user_account.last_logged_in_at": now  # Update last_logged_in_at for every login
            },
            "$setOnInsert": {
                "user_account.primary_email": primary_email.lower().strip(),
                "user_profile.display_name": user_given_name.title().strip(),
                "user_profile.avatar_url": f'https://api.dicebear.com/9.x/notionists/svg?seed={user_info.get("givenName", "User").title()}',
                "user_account.user_id": str(uuid.uuid4()),
                "user_account.role": "user",
                "user_account.created_at": now,  # Set created_at only on insert
                "user_account.is_active": True,
            },
        },
        upsert=True,
    )

    if update_result.acknowledged:
        session["is_authenticated"] = True
        session["user"] = mongodb_client.users.find_one(
            {"user_account.primary_email": primary_email}, {"_id": 0}
        )
        return redirect(url_for("homepage"))

    return (
        jsonify(
            {
                "response_code": 400,
                "message": "Failed to update user info",
                "identifier": str(uuid.uuid4()),
            }
        ),
        400,
    )


# User endpoints
@app.route("/api/v1/user", methods=["POST", "GET"])
def create_user():
    if session.get("is_authenticated"):
        return jsonify(
            {
                "response_code": 200,
                "data": session["user"],
                "identifier": str(uuid.uuid4()),
            }
        )
    return (
        jsonify(
            {
                "response_code": 401,
                "message": "Unauthorized",
                "identifier": str(uuid.uuid4()),
            }
        ),
        401,
    )


# System endpoints
@app.route("/api/v1/create-announcement", methods=["POST"])
def create_announcement_api():
    if session.get("is_authenticated"):
        announcement_title = request.form.get("announcement_title")
        announcement_body = request.form.get("ckeditor")

        if announcement_title and announcement_body:
            mongodb_client.announcements.insert_one(
                {
                    "announcement_id": str(uuid.uuid4()),
                    "announcement_title": announcement_title,
                    "announcement_body": announcement_body,
                    "created_at": datetime.now(),
                    "is_active": True,
                }
            )
            return redirect(url_for("create_announcement"))
        return (
            jsonify(
                {
                    "response_code": 400,
                    "message": "Announcement title and body are required",
                    "identifier": str(uuid.uuid4()),
                }
            ),
            400,
        )


@app.route("/api/v1/announcements/toogle-visibility", methods=["POST"])
def toogle_visibility():
    if (
        session.get("is_authenticated")
        and session["user"]["user_account"]["role"] == "admin"
    ):
        announcement_id = request.form.get("announcement_id")
        announcement = mongodb_client.announcements.find_one(
            {"announcement_id": announcement_id}
        )
        if announcement:
            mongodb_client.announcements.update_one(
                {"announcement_id": announcement_id},
                {"$set": {"is_active": not announcement["is_active"]}},
            )
            return redirect(url_for("announcement", announcement_id=announcement_id))
        return redirect(url_for(request.url))
    return (
        jsonify(
            {
                "response_code": 401,
                "message": "Unauthorized",
                "identifier": str(uuid.uuid4()),
            }
        ),
        401,
    )


@app.route("/api/v1/create-problem", methods=["POST"])
def create_problem_api():
    if (
        session.get("is_authenticated")
        and session["user"]["user_account"]["role"] == "admin"
    ):
        problem_title = request.form.get("problem_title")
        problem_description = request.form.get("ckeditor")
        problem_stdin = request.form.get("problem_stdin")
        problem_stdout = request.form.get("problem_stdout")
        problem_level = request.form.get("problem_level")
        problem_tags = request.form.get("problem_tags")

        if (
            problem_title
            and problem_description
            and problem_stdin
            and problem_stdout
            and problem_level
            and problem_tags
        ):
            mongodb_client.problems.insert_one(
                {
                    "problem_id": str(uuid.uuid4()),
                    "problem_title": problem_title,
                    "problem_description": problem_description,
                    "problem_stdin": problem_stdin.strip(),
                    "problem_stdout": problem_stdout.strip(),
                    "problem_level": problem_level,
                    "problem_tags": [tag.strip() for tag in problem_tags.split(",")],
                    "created_at": datetime.now(),
                    "is_visible": False,
                    "is_part_of_competition": False,
                    "competition_id": None,
                    "problem_statistics": {
                        "total_submissions": 0,
                        "total_accepted_submissions": 0,
                        "total_rejected_submissions": 0,
                        "total_runtime_error_submissions": 0,
                        "total_time_limit_exceeded_submissions": 0,
                        "total_memory_limit_exceeded_submissions": 0,
                        "total_compilation_error_submissions": 0,
                        "total_internal_error_submissions": 0,
                        "total_other_error_submissions": 0,
                    },
                }
            )
            return redirect(url_for("create_problem"))
        return (
            jsonify(
                {
                    "response_code": 400,
                    "message": "Problem title, description, stdin, stdout, level and tags are required",
                    "identifier": str(uuid.uuid4()),
                }
            ),
            400,
        )


@app.route("/api/v1/submissions", methods=["POST"])
def create_submission():
    if session.get("is_authenticated"):
        problem_id = request.json.get("problem_id")
        code = request.json.get("code")
        if problem_id and code:
            problem = mongodb_client.problems.find_one({"problem_id": problem_id})
            if problem:
                # Prepare data to send to Judge0 in base64 encoded format
                judge0_payload = {
                    "source_code": code,
                    "stdin": base64.b64encode(problem.get("problem_stdin", "").encode()).decode(),
                    "expected_output": base64.b64encode(problem.get("problem_stdout", "").encode()).decode(),
                    "language_id": get_language_id(
                        request.json.get("language", "python")
                    ),
                }

                # Send submission to the Judge0 API
                judge0_response = requests.post(
                    "https://judge0-ce.p.sulu.sh/submissions?base64_encoded=true",
                    json=judge0_payload,
                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.getenv("API_KEY")},
                )

                # Check if the submission was successful
                if judge0_response.status_code == 201:

                    submission_id = str(uuid.uuid4())
                    mongodb_client.submissions.insert_one(
                        {
                            "submission_id": submission_id,
                            "judge0_submission_id": judge0_response.json()["token"],
                            "problem_id": problem_id,
                            "user_id": session["user"]["user_account"]["user_id"],
                            "code": code,
                            "language": request.json.get("language", "python"),
                            "submission_status": {
                                "status_code": 0,
                                "status": "In Queue",
                                "time": 0,
                                "memory": 0,
                            },
                            "created_at": datetime.now(),
                            "updated_at": datetime.now(),
                        }
                    )

                    mongodb_client.problems.update_one(
                        {"problem_id": problem_id},
                        {
                            "$inc": {
                                "problem_statistics.total_submissions": 1,
                            }
                        },
                    )

                    return jsonify(
                        {
                            "response_code": 200,
                            "message": "Submission created",
                            "submission_id": submission_id,
                            "submission_result_url": f"/api/v1/submissions/{submission_id}",
                        }
                    )

                else:
                    return (
                        jsonify(
                            {
                                "response_code": 500,
                                "message": "Failed to submit to Judge0",
                                "details": judge0_response.json(),
                            }
                        ),
                        500,
                    )

            return (
                jsonify(
                    {
                        "response_code": 404,
                        "message": "Problem not found",
                        "identifier": str(uuid.uuid4()),
                    }
                ),
                404,
            )

        return (
            jsonify(
                {
                    "response_code": 400,
                    "message": "Problem ID and code are required",
                    "identifier": str(uuid.uuid4()),
                }
            ),
            400,
        )

    return (
        jsonify(
            {
                "response_code": 401,
                "message": "Unauthorized",
                "identifier": str(uuid.uuid4()),
            }
        ),
        401,
    )


@app.route("/api/v1/submissions/<submission_id>", methods=["GET"])
def get_submission(submission_id):
    if session.get("is_authenticated"):
        submission = mongodb_client.submissions.find_one(
            {"submission_id": submission_id}
        )
        if submission and submission["user_id"] == session["user"]["user_account"]["user_id"]:
            if submission["submission_status"]["status_code"] == 0:
                judge0_response = requests.get(
                    f"https://judge0-ce.p.sulu.sh/submissions/{submission['judge0_submission_id']}",
                    headers={"Authorization": "Bearer " + os.getenv("API_KEY")},
                )
                if judge0_response.status_code == 200:

                    submission_status = judge0_response.json()

                    print(submission_status)
                    submission["submission_status"] = {
                        "status_code": submission_status["status"]["id"],
                        "status": submission_status["status"]["description"],
                        "time": submission_status["time"],
                        "memory": submission_status["memory"],
                    }
                    mongodb_client.submissions.update_one(
                        {"submission_id": submission_id},
                        {
                            "$set": {
                                "submission_status": submission["submission_status"]
                            }
                        },
                    )
                    if submission_status["status"]["id"] == 3:
                        mongodb_client.problems.update_one(
                            {"problem_id": submission["problem_id"]},
                            {
                                "$inc": {
                                    "problem_statistics.total_accepted_submissions": 1,
                                }
                            },
                        )
                        submission_status["stdout"] = "-- Hidden --"
                        return jsonify(
                            {
                                "response_code": 200,
                                "data": submission_status,
                                "identifier": str(uuid.uuid4()),
                            }
                        )
                    mongodb_client.problems.update_one(
                        {"problem_id": submission["problem_id"]},
                        {
                            "$inc": {
                                "problem_statistics.total_rejected_submissions": 1,
                            }
                        },
                    )
                    return jsonify(
                        {
                            "response_code": 200,
                            "data": submission_status,
                            "identifier": str(uuid.uuid4()),
                        }
                    )
        return (
            jsonify(
                {
                    "response_code": 404,
                    "message": "Submission not found",
                    "identifier": str(uuid.uuid4()),
                }
            ),
            404,
        )
    return (
        jsonify(
            {
                "response_code": 401,
                "message": "Unauthorized",
                "identifier": str(uuid.uuid4()),
            }
        ),
        401,
    )


def get_language_id(language):
    # Map your languages to Judge0 language IDs
    language_map = {
        "python": 71,  # Python 3
        "javascript": 63,  # JavaScript (Node.js)
        "java": 62,  # Java
        "cpp": 54,  # C++
        "c": 50,  # C
        "typescript": 74,  # TypeScript
    }
    return language_map.get(language, 34)  # Default to Python


if __name__ == "__main__":
    app.run(debug=True, port=8080)
