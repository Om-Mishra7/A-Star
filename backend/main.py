import os
import uuid
import requests
from datetime import datetime, timedelta
import base64
import random
from collections import defaultdict
import requests
import json
import difflib
import re
import redis
from dotenv import load_dotenv
from pymongo import MongoClient
from flask import Flask, request, jsonify, session, redirect, url_for, render_template, abort
from flask_session import Session
from flask_cors import CORS
from flask_ckeditor import CKEditor
from zoneinfo import ZoneInfo
import google.generativeai as genai
import secrets


# Get the current time in the "Asia/Kolkata" timezone
kolkata_tz = ZoneInfo("Asia/Kolkata")


load_dotenv()  # take environment variables from .env.

app = Flask(__name__)

# App Configuration
app.config["SESSION_TYPE"] = "redis"
app.config["SESSION_PERMANENT"] = True
app.config["SESSION_EXPIRES"] = 3600 * 24 * 30  # 30 days
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

# Gemini API Configuration
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# Middleware

@app.after_request
def headers(response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600, must-revalidate, immutable"
    if request.path.startswith(("/", "/problems", "/contests", "/users")):
        response.headers["Cache-Control"] = "private, max-age=3600, must-revalidate"
    if request.path.startswith("/api/"):
        response.headers["Content-Type"] = "application/json"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


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
            mongodb_client.announcements.find(
                {"is_active": True},
                {"_id": 0}
            ).sort("created_at", -1).limit(3)
        ),
        upcoming_contests=list(
            contests
            for contests in mongodb_client.contests.find({}, {"_id": 0})
            if datetime.strptime(
                contests["contest_start_time"], "%Y-%m-%dT%H:%M"
            ).replace(tzinfo=kolkata_tz)
            > datetime.now(tz=kolkata_tz)
        ),
        global_leaderboard= calculate_global_leaderboard(),
        past_contests = list(
            contest for contest in mongodb_client.contests.find({}, {"_id": 0}) 
            if datetime.strptime(contest["contest_end_time"], "%Y-%m-%dT%H:%M").replace(tzinfo=kolkata_tz) 
            < datetime.now(tz=kolkata_tz)
        ),
        submissions_chart = generate_submissions_chart(),
        current_year = datetime.now(tz=kolkata_tz).year,
        new_users = list(
            mongodb_client.users.find({}, {"_id": 0, "university_details.student_id": 1, "user_profile.avatar_url": 1, "user_profile.display_name": 1, "user_profile.user_id" : 1, "user_account.user_id" : 1 }, sort=[("user_account.created_at", -1)], limit=5)
            ),
        )


@app.context_processor
def format_date():
    def format_date(date, format="long"):
        if isinstance(date, str):
            # Try different date formats
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
                try:
                    date = datetime.strptime(date, fmt)
                    break
                except ValueError:
                    continue
            else:
                return date
        if format == "short":
            return date.strftime("%b %d, %Y")
        elif format == "long":
            return date.strftime("%B %d, %Y %I:%M %p")

    return dict(format_date=format_date)

def calculate_global_leaderboard():
    # Create a dictionary to store the aggregated scores
    global_leaderboard = defaultdict(lambda: {"score": 0, "problems_solved": 0})

    # Iterate through all contests
    for contest in mongodb_client.contests.find({}, {"_id": 0, "contest_end_time": 1, "contest_statistics": 1}):
        # Convert contest end time to a datetime object
        contest_end_time = datetime.strptime(contest["contest_end_time"], "%Y-%m-%dT%H:%M").replace(tzinfo=kolkata_tz)

        # Only consider contests that have ended
        if contest_end_time < datetime.now(tz=kolkata_tz):
            contest_leaderboard = contest["contest_statistics"]["contest_leaderboard"]
            
            # Iterate through each user in the contest leaderboard

            if isinstance(contest_leaderboard, list):
                contest_leaderboard = {user["user_id"]: user for user in contest_leaderboard}
            for user_id, user_data in contest_leaderboard.items():
                global_leaderboard[user_id]["score"] += user_data["score"]
                global_leaderboard[user_id]["problems_solved"] += sum(
                    1 for problem in user_data["problems"] 
                    if user_data["problems"][problem]["has_accepted_submission"]
                )

    # Convert the global leaderboard to a sorted list by score
    for user_id in global_leaderboard:
        global_leaderboard[user_id]["profile"] = mongodb_client.users.find_one({"user_account.user_id": user_id}, {"_id": 0, "user_profile": 1, "user_account": 1})
    sorted_global_leaderboard = sorted(global_leaderboard.items(), key=lambda x: x[1]["score"], reverse=True)

    return sorted_global_leaderboard

def generate_submissions_chart():
    # Dictonary of last seven days with the date as the key and the number of submissions as the value
    submissions_chart = defaultdict(int)

    # Get the current date
    current_date = datetime.now(tz=kolkata_tz)

    for i in range(6, -1, -1):
        # Get the date of the current iteration
        date = current_date - timedelta(days=i)

        # Get the submissions for the current date
        submissions = mongodb_client.submissions.count_documents(
            {
                "created_at": {
                    "$gte": date.replace(hour=0, minute=0, second=0),
                    "$lt": date.replace(hour=23, minute=59, second=59),
                }
            }
        )

        # Add the submissions to the chart
        submissions_chart[date.strftime("%d-%m")] = submissions

    return submissions_chart

def is_code_similar(submitted_code, existing_code, threshold=0.8):
    similarity_ratio = difflib.SequenceMatcher(None, submitted_code, existing_code).ratio()
    return similarity_ratio >= threshold    

def calculate_score(user_id, contest_id):
    contest = mongodb_client.contests.find_one({"contest_id": contest_id})
    leaderboard = contest["contest_statistics"]["contest_leaderboard"]
    user_score = 0
    for problem in contest["contest_problems"].values():
        if leaderboard[user_id]["problems"][problem]["has_accepted_submission"]:
            user_score += (
                20
                if problem == contest["contest_problems"]["contest_first_problem"]
                else 30
                if problem == contest["contest_problems"]["contest_second_problem"]
                else 50
            )
            user_score -= (
                min(
                    leaderboard[user_id]["problems"][problem][
                        "number_of_incorrect_submissions"
                    ],
                    5,
                )
                * 2
            )
            user_score += int(
                100
                / (
                    float(
                        mongodb_client.submissions.find_one(
                            {
                                "submission_id": leaderboard[user_id]["problems"][
                                    problem
                                ]["submissions_id"]
                            }
                        )["submission_status"]["time"]
                    )
                    * 1000
                )
            )
    return user_score

def is_user_allowed_to_submit_as_competition_submission(problem_id, user_id):
    if mongodb_client.problems.find_one({"problem_id": problem_id})[
        "is_part_of_competition"
    ]:
        contest_id = mongodb_client.problems.find_one({"problem_id": problem_id})[
            "competition_id"
        ]
        contest = mongodb_client.contests.find_one({"contest_id": contest_id})

        if contest is None:
            return False

        if datetime.strptime(contest["contest_end_time"], "%Y-%m-%dT%H:%M").replace(
            tzinfo=kolkata_tz
        ) < datetime.now(tz=kolkata_tz):
            return False
        if datetime.strptime(contest["contest_start_time"], "%Y-%m-%dT%H:%M").replace(
            tzinfo=kolkata_tz
        ) > datetime.now(tz=kolkata_tz):
            return False
        if user_id not in contest["contest_statistics"]["contest_participants"]:
            return False
        return True

def add_competition_submission(submission_id):
    submission = mongodb_client.submissions.find_one({"submission_id": submission_id})
    problem = mongodb_client.problems.find_one({"problem_id": submission["problem_id"]})
    contest_id = problem["competition_id"]
    contest = mongodb_client.contests.find_one({"contest_id": contest_id})
    user_id = submission["user_id"]

    if is_user_allowed_to_submit_as_competition_submission(submission["problem_id"], user_id):
        # Ensure that contest_leaderboard is an object (not an array)
        leaderboard = contest["contest_statistics"].get("contest_leaderboard", {})
        
        if isinstance(leaderboard, list):
            # If it's an array, replace it with an empty document
            mongodb_client.contests.update_one(
                {"contest_id": contest_id},
                {"$set": {"contest_statistics.contest_leaderboard": {}}}
            )
            leaderboard = {}

        # Check if the user is already in the leaderboard
        if user_id not in leaderboard:
            # Initialize the user's entry in the leaderboard
            new_entry = {
                "score": 0,
                "problems": {
                    contest["contest_problems"]["contest_first_problem"]: {
                        "submissions_id": None,
                        "has_accepted_submission": False,
                        "number_of_incorrect_submissions": 0,
                    },
                    contest["contest_problems"]["contest_second_problem"]: {
                        "submissions_id": None,
                        "has_accepted_submission": False,
                        "number_of_incorrect_submissions": 0,
                    },
                    contest["contest_problems"]["contest_third_problem"]: {
                        "submissions_id": None,
                        "has_accepted_submission": False,
                        "number_of_incorrect_submissions": 0,
                    },
                },
            }
            # Add new entry to the leaderboard document
            mongodb_client.contests.update_one(
                {"contest_id": contest_id},
                {
                    "$set": {
                        f"contest_statistics.contest_leaderboard.{user_id}": new_entry
                    }
                },
            )

        # If submission is accepted, update the leaderboard
        if submission["submission_status"]["status_code"] == 3:
            leaderboard = mongodb_client.contests.find_one({"contest_id": contest_id})[
                "contest_statistics"
            ]["contest_leaderboard"]

            if not leaderboard[user_id]["problems"][problem["problem_id"]][
                "has_accepted_submission"
            ]:
                # Update the accepted submission details
                mongodb_client.contests.update_one(
                    {"contest_id": contest_id},
                    {
                        "$set": {
                            f"contest_statistics.contest_leaderboard.{user_id}.problems.{problem['problem_id']}": {
                                "submissions_id": submission_id,
                                "has_accepted_submission": True,
                                "number_of_incorrect_submissions": leaderboard[user_id][
                                    "problems"
                                ][problem["problem_id"]][
                                    "number_of_incorrect_submissions"
                                ],
                            }
                        }
                    },
                )
            else:
                # If user has already submitted an accepted solution, update only if the new one has a better score (faster time)
                previous_submission = mongodb_client.submissions.find_one(
                    {
                        "submission_id": leaderboard[user_id]["problems"][
                            problem["problem_id"]
                        ]["submissions_id"]
                    }
                )
                if previous_submission["submission_status"]["time"] > submission["submission_status"]["time"]:
                    mongodb_client.contests.update_one(
                        {"contest_id": contest_id},
                        {
                            "$set": {
                                f"contest_statistics.contest_leaderboard.{user_id}.problems.{problem['problem_id']}": {
                                    "submissions_id": submission_id,
                                    "has_accepted_submission": True,
                                    "number_of_incorrect_submissions": leaderboard[
                                        user_id
                                    ]["problems"][problem["problem_id"]][
                                        "number_of_incorrect_submissions"
                                    ],
                                }
                            }
                        },
                    )

            # Recalculate the user's score and update the leaderboard
            user_score = calculate_score(user_id, contest_id)
            mongodb_client.contests.update_one(
                {"contest_id": contest_id},
                {
                    "$set": {
                        f"contest_statistics.contest_leaderboard.{user_id}.score": user_score
                    }
                },
            )

            return True

        else:
            # If submission is rejected, update the number of incorrect submissions
            if not leaderboard[user_id]["problems"][problem["problem_id"]][
                "has_accepted_submission"
            ]:
                mongodb_client.contests.update_one(
                    {"contest_id": contest_id},
                    {
                        "$set": {
                            f"contest_statistics.contest_leaderboard.{user_id}.problems.{problem['problem_id']}": {
                                "submissions_id": None,
                                "has_accepted_submission": False,
                                "number_of_incorrect_submissions": leaderboard[
                                    user_id
                                ]["problems"][problem["problem_id"]][
                                    "number_of_incorrect_submissions"
                                ]
                                + 1,
                            }
                        }
                    },
                )

            return True

    return False

def calculate_error_rate():
    total_api_calls_today = mongodb_client.platform_logs.count_documents(
        {
            "created_at": {
                "$gte": datetime.now().replace(hour=0, minute=0, second=0)
            }
        }
    )
    total_error_calls_today = mongodb_client.platform_logs.count_documents(
        {
            "created_at": {
                "$gte": datetime.now().replace(hour=0, minute=0, second=0)
            },
            "log_type": "error",
        }

    )

    if total_api_calls_today == 0:
        return "0%"
    
    return str(round((total_error_calls_today / total_api_calls_today) * 100, 2)) + "%"

def compare_output(submission_output, problem_id):
    problem = mongodb_client.problems.find_one({"problem_id": problem_id})
    expected_output = list(map(str.strip, problem.get("problem_stdout").split("\n")))
    number_of_passed_test_cases = 0
    if submission_output is None:
        return str(number_of_passed_test_cases) + "/" + str(len(expected_output))
    submission_output = list(map(str.strip, submission_output.split("\n")))

    try:
        for i in range(len(expected_output)):
            if expected_output[i] == submission_output[i]:
                number_of_passed_test_cases += 1
    except IndexError:
        return str(number_of_passed_test_cases) + "/" + str(len(expected_output))

    return str(number_of_passed_test_cases) + "/" + str(len(expected_output))

def generate_contest_report(contest, contest_submissions, contest_problems, contest_leaderboard):
    # Set up the prompt for the generative model
    prompt = f"""
    Generate a long and detailed summary and improvement report of the contest with key points in JSON format 
    (summary: str, improvement: str). The contest data is as follows: {contest}; contest submissions: {contest_submissions}; 
    contest problems: {contest_problems}; and contest leaderboard: {contest_leaderboard}. Ensure the summary is at least 
    500 words and the improvement is at least 300 words. Use the leaderboard to analyze user performance, submissions to 
    check the entries, and problems to evaluate contest challenges. Structure the output in HTML format, with <h1> for 
    headings, <p> tags with <strong> content, and replace line breaks with <br> tags.
    """

    # Make the API request to the Gemini model
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-pro-exp-02-05:generateContent?key={os.environ['GEMINI_API_KEY']}",
        headers={"Content-Type": "application/json"},
        data=json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"}
        })
    )

    # Check for a successful response
    if response.status_code != 200:
        raise Exception(f"Request failed with status code {response.status_code}")

    # Get the generated content text
    data = response.json()
    try:
        # Parse JSON response to get 'summary' and 'improvement'
        content_text = data["candidates"][0]["content"]["parts"][0]["text"]
        content_json = json.loads(content_text)
        summary_html = content_json[0]["summary"]
        improvement_html = content_json[0]["improvement"]
    except (json.JSONDecodeError, KeyError):
        # If JSON parsing fails, use regex to extract 'summary' and 'improvement'
        print("JSON parsing failed, attempting regex extraction")
        summary_match = re.search(r'"summary":\s*"([^"]+)"', content_text)
        improvement_match = re.search(r'"improvement":\s*"([^"]+)"', content_text)

        if summary_match and improvement_match:
            summary_html = summary_match.group(1)
            improvement_html = improvement_match.group(1)
        else:
            raise ValueError("Failed to extract 'summary' and 'improvement' from content_text")

    return summary_html, improvement_html

def format_ai_text(text):
    return text

import requests
import json
import os
import subprocess

def generate_problem_using_ai(level): 
    example_problem_description = """<p><strong>Parentheses Balancing</strong></p>

    <p>You are given a collection of strings. Each string consists only of the characters '(', ')', '{', '}', '[', and ']'. Your task is to determine, for each string, whether the parentheses within it are balanced. A string is considered to have balanced parentheses if it meets the following two conditions:</p>

    <p>1. <strong>Matching Pairs:</strong> Every opening parenthesis (such as '(', '{', or '[') must have a corresponding closing parenthesis of the same type (')', '}', or ']' respectively).</p>

    <p>2. <strong>Correct Order:</strong> The parentheses must be closed in the correct order. For instance, '({[]})' is balanced, while '([)]' is not because the closing square bracket ']' appears before the closing parenthesis ')'.</p>

    <p> </p>

    <p><strong>Example:</strong></p>

    <p>For example, the string '()[]{}' would be considered balanced, while the string '([)]' would not be considered balanced.</p>

    <p> </p>

    <p><strong>Input Format:</strong></p>

    <p>The input consists of multiple lines separated by \n, starting with a single integer, N, representing the number of test cases. Each of the following N lines contains a string made up of only the characters (, ), {, }, [, and ]. Each string is a sequence of these characters with no spaces in between.<br />
     </p>

    <p><strong>Output Format:</strong></p>

    <p>For each input string, output a single line containing either 'YES' if the parentheses are balanced or 'NO' if they are not.</p>

    <p><br />
    <strong>Input Example 1:</strong></p>

    <div style="background:#eeeeee; border:1px solid #cccccc; padding:5px 10px"><code>3<br />
    ()[]{}<br />
    ([)]<br />
    {{{(</code></div>

    <p><strong>Output Example 1:</strong></p>

    <div style="background:#eeeeee; border:1px solid #cccccc; padding:5px 10px"><code>YES<br />
    NO<br />
    NO</code></div>"""

    # --- Build the prompt ---
    prompt = f"""
    Generate a unique competitive programming problem suitable for difficulty level '{level}'.  The problem should be original and not similar to existing problems. Avoid problems directly related to or easily derived from these titles: {[doc['problem_title'] for doc in mongodb_client.problems.find({}, {"problem_title": 1}).sort("created_at", -1)]}.

    **Requirements:**

    1.  **Structure:**  Follow the structure outlined below (Title, Description, Input Format, Output Format, Examples, Test Cases).  Use HTML formatting as demonstrated in the example problem description.
    2.  **Uniqueness:** The problem must be distinct and not a minor variation of a well-known problem.
    3.  **Difficulty:**  Maintain the specified difficulty level consistently throughout the problem (description, test cases, solution complexity).
    4.  **Clarity:**  The problem description must be unambiguous and easy to understand.  Use clear and concise language.
    5.  **Multiple Examples:**  Provide *at least three* distinct input/output examples in the "Examples" section. These examples should cover different aspects of the problem.
    6.  **Test Cases:** Generate *at least 20* diverse test cases.  Include:
        *   **Normal Cases:**  Typical inputs and outputs.
        *   **Edge Cases:**  Inputs at the boundaries of the problem constraints.
        *   **Corner Cases:**  Unusual or tricky inputs that might expose flaws in a naive solution.
        *   **Large Inputs:** Test cases with large input sizes to check for efficiency.
    7.  **Solution:**  Provide a *correct and efficient* solution in Python.  This solution will be used to automatically generate the `problem_stdout` from the `problem_stdin`.
    8.   **Input/Output Format:** Input consists of multiple test cases. The first line contains a single integer T (number of test cases). Each set of lines describes a test case. Be specific about what each line or set of lines in each test case represents. For *each* test case, provide the corresponding output in the specified format.

    **Example Problem Description (for formatting reference):**

    {example_problem_description}

    **Output JSON Structure (Strictly Adhere to This):**

    ```json
    {{
        "problem_title": "string",
        "problem_description": "string",
        "problem_stdin": "string",
        "problem_stdout": "string",  // This will be generated, but include the key
        "problem_level": "{level}",
        "problem_tags": ["tag1", "tag2", ...],
        "solution": "python code string"
    }}
    ```

    **Generate the problem now, following all instructions carefully.**
    """
    # --- End of Prompt ---

    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-pro-exp-02-05:generateContent?key=" + os.environ["GEMINI_API_KEY"],
        headers={"Content-Type": "application/json"},
        data=json.dumps(
            {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": prompt
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "temperature": 0.7,  # Adjust for creativity (0.7 is a good balance)
                    "maxOutputTokens": 8000, # Add to prevent trunctation
                    "topP": 0.95,
                    "topK": 40,
                }
            }
        ),
    )

    if response.status_code != 200:
        print(f"Error: Gemini API request failed with status code {response.status_code}")
        print(response.text)  # Print the error response for debugging
        return None

    try:
        data = response.json()
        content_text = data["candidates"][0]["content"]["parts"][0]["text"]
        problem_data = json.loads(content_text)

        # --- Solution Execution and Output Generation ---
        problem_stdin = problem_data.get("problem_stdin", "")
        solution_code = problem_data.get("solution", "")

        if not problem_stdin or not solution_code:
            print("Error: Missing stdin or solution code.")
            return None
        
        # Save solution to a temporary file
        with open("temp_solution.py", "w") as f:
            f.write(solution_code)
        #Run the solution with stdin and capture stdout
        try:
            process = subprocess.run(
                ["python3", "temp_solution.py"],
                input=problem_stdin,
                text=True,
                capture_output=True,
                check=True,  # Raise an exception if the process fails
                timeout=10   # 10-second timeout
            )
            problem_stdout = process.stdout
            problem_data["problem_stdout"] = problem_stdout #Correct stdout

        except subprocess.CalledProcessError as e:
            print(f"Error: Solution execution failed. Return code: {e.returncode}")
            print(f"Stderr:\n{e.stderr}")
            return None
        except subprocess.TimeoutExpired:
            print("Error: Solution timed out.")
            return None
        finally:
            # Clean up the temporary file
            if os.path.exists("temp_solution.py"):
                os.remove("temp_solution.py")
        # --- End of Solution Execution ---

        return (
            problem_data.get("problem_title", ""),
            problem_data.get("problem_description", ""),
            problem_stdin,  # Use the original stdin
            problem_stdout, # Use generated stdout
            problem_data.get("problem_level", ""),
            problem_data.get("problem_tags", []),
        )

    except (KeyError, json.JSONDecodeError, IndexError) as e:
        print(f"Error processing API response: {e}")
        print(f"Response content:\n{response.text}")  # Print raw response for debugging
        return None
    
# Frontend endpoints

@app.route("/users", methods=["GET"])
def users():
    if session.get("is_authenticated") is None or session["user"]["user_account"]["role"] != "admin":
        return redirect(url_for("homepage"))
    return render_template("users.html", users=list(mongodb_client.users.find({}, {"_id": 0})))

@app.route("/users/<user_id>", methods=["GET"])
def user(user_id):
    user = mongodb_client.users.find_one({"user_account.user_id": user_id})
    if user is None:
        abort(404)

    # Number of submissions by user 
    total_submissions = mongodb_client.submissions.count_documents({"user_id": user["user_account"]["user_id"]})
    # Number of accepted submissions by user
    total_accepted_submissions = mongodb_client.submissions.count_documents({"user_id": user["user_account"]["user_id"], "submission_status.status_code": 3})
    # Number of problems solved by user make unique by problem id
    total_problems_solved = mongodb_client.submissions.distinct("problem_id", {"user_id": user["user_account"]["user_id"], "submission_status.status_code": 3})
    total_problems_solved = len(total_problems_solved)
    # Total number of problems
    total_problems = mongodb_client.problems.count_documents({})

    all_submissions = list(mongodb_client.submissions.find({"user_id": user["user_account"]["user_id"]}, {"_id": 0, 'submission_id': 1, 'problem_id': 1, 'language': 1, 'submission_status.status': 1}).sort("updated_at", -1))
    # Add problem title to each submission only if the problem is a part of competition that has ended
    for submission in all_submissions:
        problem = mongodb_client.problems.find_one({"problem_id": submission["problem_id"]})
        if problem is not None:
            submission["problem_title"] = problem["problem_title"]
            if problem["is_part_of_competition"]:
                contest = mongodb_client.contests.find_one({"contest_id": problem["competition_id"]})
                if contest is not None:
                    if datetime.strptime(contest["contest_end_time"], "%Y-%m-%dT%H:%M").replace(tzinfo=kolkata_tz) > datetime.now(tz=kolkata_tz):
                        submission["problem_title"] = "Hidden Due to Access Restriction"
            else:
                submission["problem_title"] = "Hidden Due to Access Restriction"
        else:
            submission["problem_title"] = "Problem Not Found"



    return render_template("user.html", user=user, total_submissions=total_submissions, total_accepted_submissions=total_accepted_submissions, total_problems_solved=total_problems_solved, total_problems=total_problems, all_submissions=all_submissions)

@app.route("/", methods=["GET"])
def homepage():
    return render_template("home.html")

@app.route("/platform-information", methods=["GET"])
def platform_information():
    if session.get("is_authenticated") is None or session["user"]["user_account"]["role"] != "admin":
        return redirect(url_for("homepage"))
    return jsonify(
        {
            "response_code": 200,
            "data": {
                "platform_name": "A*",
                "platform_version": "1.0.0",
                "platform_statistic": {
                    "total_problems": mongodb_client.problems.count_documents({}),
                    "total_contests": mongodb_client.contests.count_documents({}),
                    "total_submissions": mongodb_client.submissions.count_documents({}),
                },
                "user_statistics": {
                    "total_users": mongodb_client.users.count_documents({}),
                    "users": list(
                        mongodb_client.users.find({}, {"_id": 0, "user_account.created_at": 1, "user_account.primary_email": 1, "user_account.user_id": 1, "user_profile.display_name": 1}, sort=[("user_account.created_at", -1)])
                    ),
                },
                "submission_statistics": {
                    "total_submissions": mongodb_client.submissions.count_documents({}),
                    "submissions": list(
                        mongodb_client.submissions.find({}, {"_id": 0, "language": 1, "problem_id" : 1, "updated_at": 1, "user_id": 1}, sort=[("updated_at", -1)])
                    ),
                },
                "external_api_statistics": {
                    "total_api_calls": mongodb_client.submissions.count_documents({}),
                    "total_api_calls_today": mongodb_client.submissions.count_documents(
                        {
                            "created_at": {
                                "$gte": datetime.now().replace(hour=0, minute=0, second=0)
                            }
                        }
                    ),
                    "error_rate_today": calculate_error_rate(),
                },
                "platform_devlopers": [
                    {
                        "name": "Om Mishra",
                        "email": "hello@om-mishra.com",
                    }]
            },
            "identifier": str(uuid.uuid4()),
        }
    )

@app.route("/login", methods=["GET"])
def login():
    if session.get("is_authenticated"):
        return redirect(url_for("homepage"))
    session["auth_state"] = secrets.token_hex(16)
    return render_template("login.html", redirect_uri=f'https://accounts.om-mishra.com/api/v1/oauth2/authorize?client_id={os.getenv("CLIENT_ID")}&state={session["auth_state"]}')



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
    if session.get("is_authenticated") is None:
        return redirect(url_for("login"))

    all_problems = list(
        mongodb_client.problems.aggregate(
            [
                {"$match": {"is_part_of_competition": True}},
                {
                    "$lookup": {
                        "from": "contests",
                        "localField": "competition_id",
                        "foreignField": "contest_id",
                        "as": "contest_details",
                    }
                },
                {"$unwind": "$contest_details"},
                {
                    "$project": {
                        "_id": 1,
                        "problem_id": 1,
                        "problem_title": 1,
                        "problem_description": 1,
                        "problem_level": 1,
                        "problem_tags": 1,
                        "created_at": 1,
                        "is_visible": 1,
                        "is_part_of_competition": 1,
                        "competition_id": 1,
                        "problem_statistics": 1,
                        "contest_title": "$contest_details.contest_title",
                        "contest_start_time": "$contest_details.contest_start_time",
                        "contest_end_time": "$contest_details.contest_end_time",
                    }
                },
                {"$sort": {"contest_start_time": -1}},
            ]
        )
    )

    visible_problems = []

    for problem in all_problems:
        if datetime.strptime(problem["contest_end_time"], "%Y-%m-%dT%H:%M").replace(
            tzinfo=kolkata_tz
        ) < datetime.now(tz=kolkata_tz):
            visible_problems.append(problem)

    if session["user"]["user_account"]["role"] == "admin":
        return render_template("problems.html", all_problems=list(mongodb_client.problems.find({}, {"problem_stdin": 0, "problem_stdout": 0})))

    return render_template("problems.html", all_problems=visible_problems)


@app.route("/problems/<problem_id>", methods=["GET"])
def problem(problem_id):
    if session.get("is_authenticated") is None:
        return redirect(url_for("login"))
    problem = mongodb_client.problems.find_one({"problem_id": problem_id})
    if problem:
        top_submissions = list(
            mongodb_client.submissions.aggregate(
                [
                    {
                        "$match": {
                            "problem_id": problem_id,
                            "submission_status.status_code": 3,
                            "is_removed": False,
                        }
                    },
                    {
                        "$sort": {"submission_status.time": 1}
                    },  # Sort by fastest execution time (ascending)
                    {
                        "$group": {  # Group by user_id to ensure only one submission per user
                            "_id": "$user_id",
                            "submission_id": {
                                "$first": "$_id"
                            },  # Get the submission ID with the fastest time
                            "problem_id": {"$first": "$problem_id"},
                            "submission_status": {
                                "$first": "$submission_status"
                            },  # Fastest submission's status
                            "language": {
                                "$first": "$language"
                            },  # Fastest submission's language
                            "user_id": {"$first": "$user_id"},  # Retain the user_id
                        }
                    },
                    {
                        "$lookup": {
                            "from": "users",  # Join with users collection to fetch user details
                            "localField": "user_id",  # Field from submissions (grouped)
                            "foreignField": "user_account.user_id",  # Field from users collection
                            "as": "user_details",  # Resulting field with user details
                        }
                    },
                    {"$unwind": "$user_details"},  # Flatten the user_details array
                    {
                        "$project": {
                            "_id": 0,  # Exclude MongoDB's default ID
                            "user_id": 1,
                            "submission_id": 1,
                            "problem_id": 1,
                            "submission_status": 1,  # Includes the fastest submission's time
                            "language": 1,
                            "user_details.user_profile.display_name": 1,
                            "user_details.user_profile.avatar_url": 1,
                        }
                    },
                ]
            )
        )

        if top_submissions is not None:
            top_submissions.sort(key=lambda x: (x["submission_status"]["time"], x["submission_status"]["memory"], x["user_id"]))
        if session["user"]["user_account"]["role"] == "admin":
            return render_template(
                "individual-problem.html",
                problem=problem,
                top_submissions=top_submissions,
            )
        
        if problem.get("is_visible") is False:
            if problem.get("is_part_of_competition"):
                if datetime.strptime(
                    mongodb_client.contests.find_one(
                        {"contest_id": problem.get("competition_id")}
                    )["contest_end_time"],
                    "%Y-%m-%dT%H:%M",
                ).replace(tzinfo=kolkata_tz) < datetime.now(tz=kolkata_tz):
                    mongodb_client.problems.update_one(
                        {"problem_id": problem_id}, {"$set": {"is_visible": True}}
                    )
                    return render_template(
                        "individual-problem.html",
                        problem=problem,
                        top_submissions=top_submissions,
                    )
                else:
                    if datetime.strptime(
                        mongodb_client.contests.find_one(
                            {"contest_id": problem.get("competition_id")}
                        )["contest_start_time"],
                        "%Y-%m-%dT%H:%M",
                    ).replace(tzinfo=kolkata_tz) < datetime.now(
                        tz=kolkata_tz
                    ) and session[
                        "user"
                    ][
                        "user_account"
                    ][
                        "user_id"
                    ] in [
                        participant
                        for participant in mongodb_client.contests.find_one(
                            {"contest_id": problem.get("competition_id")}
                        )["contest_statistics"]["contest_participants"]
                    ]:
                        return render_template(
                            "individual-problem.html",
                            problem=problem,
                            top_submissions=top_submissions,
                        )
            return redirect(url_for("problems"))
        return render_template(
            "individual-problem.html", problem=problem, top_submissions=top_submissions
        )
    return redirect(url_for("homepage"))


@app.route("/contests", methods=["GET"])
def contests():
    return render_template(
        "contests.html", all_contests=list(mongodb_client.contests.find({}))
    )

@app.route("/contests/<contest_id>", methods=["GET"])
def contest(contest_id):
    if session.get("is_authenticated") is None:
        return redirect(url_for("login"))
    
    has_contest_started = False
    has_contest_ended = False
    has_user_participated = False
    
    contest = mongodb_client.contests.find_one({"contest_id": contest_id})
    if contest:
        # Check contest start and end time
        if datetime.strptime(
            contest.get("contest_start_time"), "%Y-%m-%dT%H:%M"
        ).replace(tzinfo=kolkata_tz) < datetime.now(tz=kolkata_tz):
            has_contest_started = True
        if datetime.strptime(contest.get("contest_end_time"), "%Y-%m-%dT%H:%M").replace(
            tzinfo=kolkata_tz
        ) < datetime.now(tz=kolkata_tz):
            mongodb_client.problems.update_many(
                {
                    "problem_id": {
                        "$in": [
                            contest["contest_problems"]["contest_first_problem"],
                            contest["contest_problems"]["contest_second_problem"],
                            contest["contest_problems"]["contest_third_problem"],
                        ]
                    }
                },
                {"$set": {"is_visible": True}},
            )
            has_contest_ended = True
        
        # Check if user has participated
        has_user_participated = session["user"]["user_account"]["user_id"] in [
            participant
            for participant in contest["contest_statistics"]["contest_participants"]
        ]
        
        contest_problems = mongodb_client.problems.find(
            {
                "problem_id": {
                    "$in": [
                        contest["contest_problems"]["contest_first_problem"],
                        contest["contest_problems"]["contest_second_problem"],
                        contest["contest_problems"]["contest_third_problem"],
                    ]
                }
            }
        )

        # Retrieve the leaderboard
        contest_leaderboard = mongodb_client.contests.find_one(
            {"contest_id": contest_id}
        )["contest_statistics"]["contest_leaderboard"]

        # Ensure contest_leaderboard is a dictionary (if it's a list)
        if isinstance(contest_leaderboard, list):
            contest_leaderboard = {
                user["user_id"]: user for user in contest_leaderboard
            }

        # Calculate problems solved by each user
        for user_id in contest_leaderboard:
            contest_leaderboard[user_id]["problems_solved"] = sum(
                1
                for problem in contest_leaderboard[user_id]["problems"]
                if contest_leaderboard[user_id]["problems"][problem][
                    "has_accepted_submission"
                ]
            )
            # Retrieve user profile data
            contest_leaderboard[user_id]["profile"] = mongodb_client.users.find_one(
                {"user_account.user_id": user_id}, {"_id": 0, "user_profile": 1}
            )

        # Sort the leaderboard based on score
        contest_leaderboard = dict(
            sorted(
                contest_leaderboard.items(),
                key=lambda item: item[1]["score"],
                reverse=True,
            )
        )

        # Return the appropriate response
        return render_template("individual-contest.html", 
                            contest=contest, 
                            contest_leaderboard=contest_leaderboard, 
                            has_contest_started=has_contest_started, 
                            has_contest_ended=has_contest_ended, 
                            has_user_participated=has_user_participated, 
                            contest_problems=contest_problems)
    return abort(404)


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

@app.route("/create-problem-ai", methods=["GET"])
def create_problem_ai():
    if (
        session.get("is_authenticated")
        and session["user"]["user_account"]["role"] == "admin"
    ):
        return render_template("create_problem_ai.html")
    return redirect(url_for("homepage"))

@app.route("/create-contest", methods=["GET"])
def create_contest():
    if (
        session.get("is_authenticated")
        and session["user"]["user_account"]["role"] == "admin"
    ):
        problems = list(
            mongodb_client.problems.find(
                {"is_part_of_competition": False}, {"_id": 1, "problem_title": 1, "problem_id": 1, "problem_level": 1}
            )
        )
        
        previous_contests = list(mongodb_client.contests.find({}, {"_id": 0}))
        return render_template(
            "create_contest.html",
            problems=problems,
            previous_contests=previous_contests,
        )
    return redirect(url_for("homepage"))

@app.route("/contest-results/<contest_id>", methods=["GET"])
def contest_results(contest_id):
    # Get the contest details and details about all user submissions make a leaderboard and give all submissions to Gemini to genrate a report and also create a user by report showing the user's number of submisison percent correct copied code all keys pressed and time taken
    if session.get("is_authenticated") is None:
        return redirect(url_for("login"))
    
    if session["user"]["user_account"]["role"] != "admin":
        return redirect(url_for("homepage"))
    
    contest = mongodb_client.contests.find_one({"contest_id": contest_id}, {"_id": 0, "contest_id": 1, "contest_title": 1, "contest_start_time": 1, "contest_end_time": 1, "contest_statistics": 1, "contest_problems": 1, "contest_summary": 1, "contest_improvement": 1})
    if contest:
        contest_leaderboard = mongodb_client.contests.find_one(
            {"contest_id": contest_id}
        )["contest_statistics"]["contest_leaderboard"]

        # Ensure the contest has ended
        if datetime.strptime(contest["contest_end_time"], "%Y-%m-%dT%H:%M").replace(tzinfo=kolkata_tz) > datetime.now(tz=kolkata_tz):
            return redirect(url_for("contest", contest_id=contest_id))

        # Ensure contest_leaderboard is a dictionary (if it's a list)
        if isinstance(contest_leaderboard, list):
            contest_leaderboard = {
                user["user_id"]: user for user in contest_leaderboard
            }

        # Calculate problems solved by each user
        for user_id in contest_leaderboard:
            contest_leaderboard[user_id]["problems_solved"] = sum(
                1
                for problem in contest_leaderboard[user_id]["problems"]
                if contest_leaderboard[user_id]["problems"][problem][
                    "has_accepted_submission"
                ]
            )
            # Retrieve user profile data
            contest_leaderboard[user_id]["profile"] = mongodb_client.users.find_one(
                {"user_account.user_id": user_id}, {"_id": 0, "user_profile": 1}
            )

        # Sort the leaderboard based on score
        contest_leaderboard = dict(
            sorted(
                contest_leaderboard.items(),
                key=lambda item: item[1]["score"],
                reverse=True,
            )
        )

        # Get all submissions for the contest by looping thorough all the problems of the contest then checking submissisons for the ptobelm id in the contest timeframe and at end cchecking if the user had participated in it 
        contest_submissions = []
        number_of_passed_submissions = 0
        number_of_failed_submissions = 0


        for problem_id in contest["contest_problems"].values():
            submissions = list(
                mongodb_client.submissions.find(
                    {
                        "problem_id": problem_id,
                        "user_id": {"$in": contest["contest_statistics"]["contest_participants"]},
                        "created_at": {
                            "$gte": datetime.strptime(contest["contest_start_time"], "%Y-%m-%dT%H:%M").replace(tzinfo=kolkata_tz),
                            "$lt": datetime.strptime(contest["contest_end_time"], "%Y-%m-%dT%H:%M").replace(tzinfo=kolkata_tz),
                        }
                    },
                    {"_id": 0, "problem_id": 1, "user_id": 1, "submission_status": 1, "language": 1, "created_at": 1},
                )
            )


            for submission in submissions:
                contest_submissions.append(submission)
                if submission["submission_status"]["status_code"] == 3:
                    number_of_passed_submissions += 1
                else:
                    number_of_failed_submissions += 1

        # Get title of all contest problems and thier difficulty 

        contest_problems = list(
            mongodb_client.problems.find(
                {
                    "problem_id": {
                        "$in": [
                            contest["contest_problems"]["contest_first_problem"],
                            contest["contest_problems"]["contest_second_problem"],
                            contest["contest_problems"]["contest_third_problem"],
                        ]
                    }
                },
                {"_id": 0, "problem_title": 1, "problem_description": 1, "problem_level": 1},
            )
        )

        # Check if the contest has a summary and improvement field if not make a request to Gemini to generate a report
        if contest.get("contest_summary") is None or contest.get("contest_improvement") is None:
            while True:
                contest_summary, contest_improvement = generate_contest_report(contest, contest_submissions, contest_problems, contest_leaderboard)
                if len(contest_summary) > 200 or len(contest_improvement) > 200:
                    break
            mongodb_client.contests.update_one(
                {"contest_id": contest_id},
                {
                    "$set": {
                        "contest_summary": contest_summary,
                        "contest_improvement": contest_improvement
                    }
                }
            )

        contest =  mongodb_client.contests.find_one({"contest_id": contest_id}, {"_id": 0, "contest_id": 1, "contest_title": 1, "contest_start_time": 1, "contest_end_time": 1, "contest_statistics": 1, "contest_problems": 1, "contest_summary": 1, "contest_improvement": 1})

        # For all users in the leaderboard get if any of the submissions are similar to the other submissions by checking all submissions of the user in the contest and checking if any of them have is_similar set to true
        for user_id in contest_leaderboard:
            contest_leaderboard[user_id]["similar_submissions"] = False
            for problem_id in contest["contest_problems"].values():
                submissions = list(
                    mongodb_client.submissions.find(
                        {
                            "problem_id": problem_id,
                            "user_id": user_id,
                            "created_at": {
                                "$gte": datetime.strptime(contest["contest_start_time"], "%Y-%m-%dT%H:%M").replace(tzinfo=kolkata_tz),
                                "$lt": datetime.strptime(contest["contest_end_time"], "%Y-%m-%dT%H:%M").replace(tzinfo=kolkata_tz),
                            }
                        },
                        {"_id": 0, "is_similar": 1},
                    )
                )
                for submission in submissions:
                    if submission["is_similar"]:
                        contest_leaderboard[user_id]["similar_submissions"] = True
                        break


        return render_template("contest-results.html", contest=contest, contest_leaderboard=contest_leaderboard, contest_submissions=contest_submissions, number_of_passed_submissions=number_of_passed_submissions, number_of_failed_submissions=number_of_failed_submissions, contest_problems=contest_problems, contest_summary=format_ai_text(contest["contest_summary"]), contest_improvement=format_ai_text(contest["contest_improvement"]))

# Maintainance endpoints
@app.route("/api/v1/health", methods=["GET"])
def health():
    return jsonify(
        {"response_code": 200, "message": "OK", "identifier": str(uuid.uuid4())}
    )

@app.route("/api/v1/auth/external/_handler", methods=["GET"])
def external_handler():
    if session.get("is_authenticated"):
        return redirect(url_for("homepage"))

    code = request.args.get("code")

    oauth_response = requests.post(
        "https://accounts.om-mishra.com/api/v1/oauth2/user-info",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={
            "client_id": os.getenv("CLIENT_ID"),
            "client_secret": os.getenv("CLIENT_SECRET"),
            "code": code,
        },
    )

    if oauth_response.status_code != 200:
        return redirect(
            url_for(
                "index",
                message="The authentication attempt failed, due to invalid response from GitHub!",
            )
        )
        
    user_data = oauth_response.json()["user"]

    # MongoDB user query and update
    now = datetime.utcnow()  # Current timestamp for created_at and last_logged_in_at

    # Update user details or insert if not exists
    update_result = mongodb_client.users.update_one(
        {"user_account.primary_email": user_data["user_account"]["user_primary_email"]},
        {
            "$set": {
                "user_account.last_logged_in_at": now  # Update last_logged_in_at for every login
            },
            "$setOnInsert": {
                "user_account.primary_email": user_data["user_account"]["user_primary_email"],
                "user_profile.display_name": user_data["user_profile"]["user_display_name"],
                "user_profile.avatar_url": user_data["user_profile"]["user_profile_picture"] if user_data["user_profile"].get("user_profile_picture") else f"https://api.dicebear.com/9.x/initials/png?seed={user_data['user_profile']['user_display_name']}",
                "user_account.user_id": str(uuid.uuid4()),
                "user_account.role": "user",
                "user_account.created_at": now,  # Set created_at only on insert
                "user_account.is_active": True,
                "user_account.is_verified": True,
                "university_details": {
                },
            },
        },
        upsert=True,
    )

    if update_result.acknowledged:
        session["is_authenticated"] = True
        session["user"] = mongodb_client.users.find_one(
            {"user_account.primary_email": user_data["user_account"]["user_primary_email"]}, {"_id": 0}
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
                "data": mongodb_client.users.find_one(
                    {"user_account.user_id": session["user"]["user_account"]["user_id"]},
                    {"_id": 0},
                ),
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

@app.route("/api/v1/user/university-details", methods=["POST"])
def update_university_details():
    if session.get("is_authenticated"):

        student_id = request.form.get("universityRollNumber")
        student_photo = request.files.get("profilePicture")

        if not student_id.isdigit() or len(student_id) != 10:
            return (
                jsonify(
                    {
                        "response_code": 400,
                        "message": "Student ID must be a 10 digit number",
                        "identifier": str(uuid.uuid4()),
                    }
                ),
                400,
            )

        if student_id and student_photo:
            response = requests.post(
                "https://api.cdn.om-mishra.com/v1/upload-file",
                headers={"X-Authorization": "eyJhbG"},
                files={"file": request.files.get("profilePicture")},
                data={"object_path": f"users/{session['user']['user_account']['user_id']}/profile_picture/{uuid.uuid4()}.{student_photo.filename.split('.')[-1]}"},
            )

            if response.status_code != 200:
                return jsonify({'status': 'error', 'message': 'Failed to upload image!'}), 500
            
            image_url = response.json().get('file_url')

            mongodb_client.users.update_one(
                {"user_account.user_id": session["user"]["user_account"]["user_id"]},
                {
                    "$set": {
                        "university_details.student_id": student_id,
                        "university_details.student_photo": image_url,
                        "user_profile.avatar_url": image_url,
                    }
                }
            )

            session["user"]["user_profile"]["avatar_url"] = image_url

            return jsonify(
                {
                    "response_code": 200,
                    "message": "University details updated successfully",
                    "identifier": str(uuid.uuid4()),
                }
            )
        print(student_id, student_photo)
        return (
            jsonify(
                {
                    "response_code": 400,
                    "message": "Student ID and student photo are required",
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
                    "created_at": datetime.now(tz=kolkata_tz),
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

        if problem_description is None:
            problem_description = request.form.get("problem_description")

        if (
            problem_title
            and problem_description
            and problem_stdin
            and problem_stdout
            and problem_level
            and problem_tags
        ):
            problem_id = str(uuid.uuid4())
            mongodb_client.problems.insert_one(
                {
                    "problem_id": problem_id,
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
                    },
                }
            )
            
            return redirect(f"/problems/{problem_id}")
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
    is_similar = False
    if session.get("is_authenticated"):
        last_submission = mongodb_client.submissions.find_one(
            {
                "user_id": session["user"]["user_account"]["user_id"],
                "created_at": {"$gte": datetime.now() - timedelta(seconds=10)},
            }
        )
        if last_submission:
            return (
                jsonify(
                    {
                        "response_code": 429,
                        "message": "Please wait 10 seconds before submitting again",
                        "identifier": str(uuid.uuid4()),
                    }
                ),
                429,
            )
        problem_id = request.json.get("problem_id")
        code = request.json.get("code")
        if problem_id and code:
            problem = mongodb_client.problems.find_one({"problem_id": problem_id})
            if problem:
                # Prepare data to send to Judge0 in base64 encoded format
                judge0_payload = {
                    "source_code": code,
                    "stdin": base64.b64encode(
                        problem.get("problem_stdin", "").encode()
                    ).decode(),
                    "expected_output": base64.b64encode(
                        problem.get("problem_stdout", "").encode()
                    ).decode(),
                    "language_id": get_language_id(
                        request.json.get("language", "python")
                    ),
                }

                # Send submission to the Judge0 API
                judge0_response = requests.post(
                    "https://judge0-ce.p.rapidapi.com/submissions?base64_encoded=true",
                    json=judge0_payload,
                    headers={
                        "Content-Type": "application/json",
                        'x-rapidapi-key': random.choice(os.getenv("API_KEY").split(",")),
                        'x-rapidapi-host': "judge0-ce.p.rapidapi.com",
                    },
                )

                # Check if the submission was successful
                if judge0_response.status_code == 201:
                    mongodb_client.system_logs.insert_one(
                        {
                            "log_id": str(uuid.uuid4()),
                            "log_type": "info",
                            "log_message": "Submitted to execution server",
                            "log_details": judge0_response.json(),
                            "created_at": datetime.now(),
                        }
                    )
                    submission_id = str(uuid.uuid4())
                    
                    # Check if there's similar code in previous submissions
                    existing_submissions = mongodb_client.submissions.find({
                        "problem_id": problem_id
                    })
                    
                    for submission in existing_submissions:
                        existing_code = submission["code"]
                        if is_code_similar(code, existing_code) and submission["user_id"] != session["user"]["user_account"]["user_id"]:
                            is_similar = True
                            break
                            
                    
                    # Proceed with inserting the submission
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
                            "user_activity": {
                                "key_strokes": request.json.get("key_strokes", 0),
                                "focus_events": request.json.get("focus_events", 0),
                            },
                            "is_similar": is_similar,
                            "created_at": datetime.now(),
                            "updated_at": datetime.now(),
                            "is_removed": False,
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
                    mongodb_client.system_logs.insert_one(
                        {
                            "log_id": str(uuid.uuid4()),
                            "log_type": "error",
                            "log_message": "Failed to submit to execution server",
                            "log_details": judge0_response.json(),
                            "created_at": datetime.now(),
                        }
                    )
                    return (
                        jsonify(
                            {
                                "response_code": 500,
                                "message": "Failed to submit to execution server",
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
        if (
            submission
            and submission["user_id"] == session["user"]["user_account"]["user_id"]
        ):

            judge0_response = requests.get(
                f"https://judge0-ce.p.rapidapi.com/submissions/{submission['judge0_submission_id']}?fields=stdout,stderr,status,time,memory",
                headers={
                    'x-rapidapi-key': random.choice(os.getenv("API_KEY").split(",")),
                    'x-rapidapi-host': "judge0-ce.p.rapidapi.com",
                },
            )


            if judge0_response.status_code == 200:

                number_of_passed_test_cases = compare_output(
                    judge0_response.json()["stdout"], submission["problem_id"]
                )

                submission_status = judge0_response.json()
                

                submission["submission_status"] = {
                    "status_code": submission_status["status"]["id"],
                    "status": submission_status["status"]["description"],
                    "time": submission_status["time"],
                    "memory": submission_status["memory"],
                    "number_of_passed_test_cases": number_of_passed_test_cases,
                }
                mongodb_client.submissions.update_one(
                    {"submission_id": submission_id},
                    {"$set": {"submission_status": submission["submission_status"]}},
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
                    add_competition_submission(submission_id)
                    return jsonify(
                        {
                            "response_code": 200,
                            "data": submission_status,
                            "identifier": str(uuid.uuid4()),
                        }
                    )
                elif submission_status["stdout"] != None:
                    mongodb_client.problems.update_one(
                        {"problem_id": submission["problem_id"]},
                        {
                            "$inc": {
                                "problem_statistics.total_rejected_submissions": 1,
                            }
                        },
                    )
                    submission_status[
                        "number_of_passed_test_cases"
                    ] = number_of_passed_test_cases
                    add_competition_submission(submission_id)

                    return jsonify(
                        {
                            "response_code": 200,
                            "data": submission_status,
                            "identifier": str(uuid.uuid4()),
                        }
                    )
                else:
                    add_competition_submission(submission_id)

                    return (
                        jsonify(
                            {
                                "response_code": 200,
                                "data": submission_status,
                                "identifier": str(uuid.uuid4()),
                            }
                        ),
                        200,
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


@app.route("/api/v1/create-contest", methods=["POST"])
def create_contest_api():
    if (
        session.get("is_authenticated")
        and session["user"]["user_account"]["role"] == "admin"
    ):
        contest_title = request.form.get("contest_title")
        contest_start_time = request.form.get("contest_start_time")
        contest_end_time = request.form.get("contest_end_time")
        contest_first_problem = request.form.get("contest_first_problem")
        contest_second_problem = request.form.get("contest_second_problem")
        contest_third_problem = request.form.get("contest_third_problem")
        contest_body = request.form.get("ckeditor")

        contest_id = str(uuid.uuid4())

        if (
            contest_title
            and contest_start_time
            and contest_end_time
            and contest_body
            and contest_first_problem
            and contest_second_problem
            and contest_third_problem
        ):
            mongodb_client.contests.insert_one(
                {
                    "contest_id": contest_id,
                    "contest_title": contest_title,
                    "contest_start_time": contest_start_time,
                    "contest_end_time": contest_end_time,
                    "contest_problems": {
                        "contest_first_problem": contest_first_problem,
                        "contest_second_problem": contest_second_problem,
                        "contest_third_problem": contest_third_problem,
                    },
                    "contest_description": contest_body,
                    "created_at": datetime.now(),
                    "contest_statistics": {
                        "total_participants": 0,
                        "total_accepted_submissions": {
                            contest_first_problem: 0,
                            contest_second_problem: 0,
                            contest_third_problem: 0,
                        },
                        "total_rejected_submissions": {
                            contest_first_problem: 0,
                            contest_second_problem: 0,
                            contest_third_problem: 0,
                        },
                        "contest_participants": [],
                        "contest_leaderboard": [],
                    },
                }
            )
            mongodb_client.problems.update_one(
                {"problem_id": contest_first_problem},
                {
                    "$set": {
                        "is_part_of_competition": True,
                        "competition_id": contest_id,
                    }
                },
            )

            mongodb_client.problems.update_one(
                {"problem_id": contest_second_problem},
                {
                    "$set": {
                        "is_part_of_competition": True,
                        "competition_id": contest_id,
                    }
                },
            )

            mongodb_client.problems.update_one(
                {"problem_id": contest_third_problem},
                {
                    "$set": {
                        "is_part_of_competition": True,
                        "competition_id": contest_id,
                    }
                },
            )

            return redirect(url_for("create_contest"))
        return (
            jsonify(
                {
                    "response_code": 400,
                    "message": "Contest title, start time, end time and body are required",
                    "identifier": str(uuid.uuid4()),
                }
            ),
            400,
        )



@app.route("/api/v1/contest/register/<contest_id>", methods=["POST"])
def register_contest(contest_id):
    if session.get("is_authenticated"):
        contest = mongodb_client.contests.find_one({"contest_id": contest_id})

        if contest:
            if session["user"]["user_account"]["user_id"] not in [
                participant
                for participant in contest["contest_statistics"]["contest_participants"]
            ]:
                mongodb_client.contests.update_one(
                    {"contest_id": contest_id},
                    {
                        "$push": {
                            "contest_statistics.contest_participants": session["user"][
                                "user_account"
                            ]["user_id"]
                        },
                        "$inc": {
                            "contest_statistics.total_participants": 1,
                        },
                    },
                )
                return redirect(url_for("contest", contest_id=contest_id))
            return redirect(url_for("contest", contest_id=contest_id))
        return redirect(url_for("contests"))
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


@app.route("/api/v1/ai/create-problem", methods=["GET"])
def create_ai_problem():
    if session.get("is_authenticated") and session["user"]["user_account"]["role"] == "admin":
        problem_difficulty = request.args.get("difficulty")
        response = generate_problem_using_ai(problem_difficulty)
        problem_title, problem_description, problem_stdin, problem_stdout, problem_level, problem_tags = response

        try:
            return jsonify(
                {
                    "response_code": 200,
                    "problem_title": problem_title.replace("\n", "<br>"),
                    "problem_description": problem_description.replace("\n\n", "<br>").replace("\n", "<br>"),
                    "problem_stdin": problem_stdin,
                    "problem_stdout": problem_stdout,
                    "problem_level": problem_level,
                    "problem_tags": ",".join(tag.strip().replace('"', '').title() for tag in problem_tags),
                    "identifier": str(uuid.uuid4()),
                }
                )
        except Exception as e:
            print(e)
            return jsonify(
                {
                    "response_code": 500,
                    "message": "Failed to generate problem",
                    "identifier": str(uuid.uuid4()),
                }
            ), 500
    return redirect(url_for("homepage"))



@app.errorhandler(404)
def page_not_found(e):
    return jsonify(
        {
            "response_code": 404,
            "message": "Page not found",
            "identifier": str(uuid.uuid4()),
        }
    ), 404

@app.errorhandler(500)
def internal_server_error(e):
    return jsonify(
        {
            "response_code": 500,
            "message": "Internal server error",
            "identifier": str(uuid.uuid4()),
        }
    ), 500

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify(
        {
            "response_code": 405,
            "message": "Method not allowed",
            "identifier": str(uuid.uuid4()),
        }
    ), 405

@app.errorhandler(400)
def bad_request(e):
    return jsonify(
        {
            "response_code": 400,
            "message": "Bad request",
            "identifier": str(uuid.uuid4()),
        }
    ), 400


if __name__ == "__main__":
    if os.getenv("ENVIROMENT") == "development":
        app.run(host="0.0.0.0", port=5000, debug=True)
    elif os.getenv("ENVIROMENT") == "production":
        app.run(host="0.0.0.0", port=5000, debug=False)