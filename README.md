# A* - Community Competition Platform

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-2.x-orange.svg)](https://flask.palletsprojects.com/)
[![MongoDB](https://img.shields.io/badge/database-MongoDB-green.svg)](https://www.mongodb.com/)
[![Redis](https://img.shields.io/badge/cache/session-Redis-red.svg)](https://redis.io/)

A* is a web-based platform built with Flask designed for hosting competitive programming contests, managing problems, tracking user submissions, and fostering a coding community. It integrates external services like Judge0 for code execution and Google Gemini for AI-powered features.

## Table of Contents

1.  [Features](#features)
2.  [Technology Stack](#technology-stack)
3.  [Prerequisites](#prerequisites)
4.  [Installation & Setup](#installation--setup)
5.  [Configuration (`.env`)](#configuration-env)
6.  [Running the Application](#running-the-application)
7.  [Project Structure](#project-structure)
8.  [Key Features & Logic](#key-features--logic)
9.  [API Endpoints](#api-endpoints)
    *   [Frontend Routes](#frontend-routes)
    *   [Backend API Routes](#backend-api-routes)
10. [Contributing](#contributing)
11. [License](#license)

## Features

*   **User Management:**
    *   OAuth2 based login/authentication via an external provider (`accounts.om-mishra.com`).
    *   Session management using Redis.
    *   User profile pages displaying statistics (submissions, solved problems) and recent activity.
    *   Ability for users to update university details (Roll Number, Profile Picture).
    *   Admin role for managing platform content.
    *   AI-generated user summaries.
*   **Problem Management:**
    *   View list of problems (filtered for non-admins based on contest end times).
    *   View individual problem details (description, examples, constraints).
    *   Code submission interface (supports Python, Java, C++, C, JavaScript, TypeScript).
    *   Submission status tracking (In Queue, Processing, Accepted, Wrong Answer, Time Limit Exceeded, etc.).
    *   Display fastest accepted submissions ("Top Submissions") per problem.
    *   Admin: Create new problems manually.
    *   Admin: Create new problems using Google Gemini AI.
*   **Contest Management:**
    *   View list of upcoming, ongoing, and past contests.
    *   View individual contest details (description, problems, schedule).
    *   User registration for contests.
    *   Real-time contest leaderboard (updates based on submissions during the contest).
    *   Post-contest results page with detailed leaderboard and statistics.
    *   Admin: Create new contests, linking existing problems.
    *   Admin: View AI-generated contest summary and improvement reports.
*   **Submissions:**
    *   Code execution and judging via Judge0 CE API.
    *   Detailed submission results (status, execution time, memory usage, passed test cases).
    *   Similarity check against previous submissions for the same problem.
    *   Automatic leaderboard updates for contest submissions.
    *   Rate limiting (10 seconds between submissions).
*   **Announcements:**
    *   Display global announcements on the platform.
    *   Admin: Create, manage, and toggle visibility of announcements.
*   **Leaderboards:**
    *   Contest-specific leaderboards.
    *   Global leaderboard aggregating scores from past contests.
*   **Platform Insights (Admin):**
    *   View platform statistics (users, problems, contests, submissions).
    *   View user list and submission logs.
    *   Monitor external API usage and error rates.
*   **Other:**
    *   Rich text editing using CKEditor for problem descriptions, contest details, and announcements.
    *   Global context processors to inject common data (announcements, upcoming contests, global leaderboard) into templates.
    *   Caching strategies for static assets and certain page responses.
    *   Custom error handlers (404, 500, 405, 400).

## Technology Stack

*   **Backend:** Python 3, Flask
*   **Database:** MongoDB
*   **Session Store/Cache:** Redis
*   **Templating:** Jinja2
*   **Rich Text Editor:** CKEditor (Flask-CKEditor)
*   **Code Execution:** Judge0 CE API
*   **AI Generation:** Google Gemini API
*   **Authentication:** External OAuth2 Provider (`accounts.om-mishra.com`)
*   **File Storage (Profile Pictures):** External CDN (`api.cdn.om-mishra.com`)
*   **Frontend:** HTML, CSS, JavaScript (served via Flask templates/static files)
*   **Deployment:** (Assumed) WSGI Server (like Gunicorn/uWSGI) + Web Server (like Nginx)

## Prerequisites

*   Python 3.9+ and `pip`
*   MongoDB Server (running locally or accessible URI)
*   Redis Server (running locally or accessible URI)
*   Access credentials for:
    *   External OAuth2 Provider (Client ID, Client Secret)
    *   Judge0 CE API (RapidAPI Key(s))
    *   Google Gemini API (API Key)
    *   External CDN API (Authorization Token - if required by the API)

## Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python -m venv venv
    # On Windows
    venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    Create a `requirements.txt` file with the following content (or generate it from the imports):
    ```txt
    Flask
    Flask-Session[redis]
    Flask-Cors
    Flask-CKEditor
    pymongo
    python-dotenv
    requests
    redis
    gunicorn # Or another WSGI server for production
    google-generativeai
    pytz # Although zoneinfo is used, pytz might be an indirect dependency or useful
    zoneinfo # Available in Python 3.9+ stdlib
    secrets # Available in Python stdlib
    difflib # Available in Python stdlib
    ```
    Then install:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables:**
    Create a `.env` file in the root directory and populate it with the necessary credentials and settings. See the [Configuration (`.env`)](#configuration-env) section below.

5.  **Ensure MongoDB and Redis are running and accessible.**

## Configuration (`.env`)

Create a `.env` file in the project root with the following variables:

```dotenv
# Flask App Configuration
SECRET_KEY='your_very_strong_random_secret_key' # Essential for sessions and security
ENVIROMENT='development' # 'development' or 'production'

# Database Configuration
MONGODB_URI='mongodb://localhost:27017/' # Your MongoDB connection string

# Redis Configuration (for Sessions)
REDIS_URI='redis://localhost:6379/0' # Your Redis connection string

# External APIs
GEMINI_API_KEY='your_google_gemini_api_key'
API_KEY='judge0_api_key_1,judge0_api_key_2' # Comma-separated Judge0 RapidAPI keys (used randomly)

# OAuth2 Client Configuration (accounts.om-mishra.com)
CLIENT_ID='your_oauth_client_id'
CLIENT_SECRET='your_oauth_client_secret'

# Optional: CDN API Key (if needed for api.cdn.om-mishra.com)
# CDN_API_KEY='your_cdn_api_key_or_token' # The code currently hardcodes a token header, adjust if needed
```

**Important:**
*   Replace placeholder values with your actual credentials.
*   Keep the `.env` file secure and **do not** commit it to version control. Add `.env` to your `.gitignore` file.
*   Generate a strong `SECRET_KEY`.

## Running the Application

1.  **Ensure the virtual environment is activated.**
2.  **Make sure MongoDB and Redis are running.**
3.  **Start the Flask development server:**
    ```bash
    python app.py
    ```
    Or, if configured for `flask run`:
    ```bash
    export FLASK_APP=app.py
    export FLASK_ENV=development # Optional, uses ENVIROMENT var otherwise
    flask run --host=0.0.0.0 --port=5000
    ```

4.  **Access the application:** Open your web browser and navigate to `http://localhost:5000` (or the configured host/port).

*   **For Production:** Use a production-ready WSGI server like Gunicorn or uWSGI behind a reverse proxy like Nginx. Set `ENVIROMENT='production'` in your `.env` file.

    ```bash
    gunicorn --bind 0.0.0.0:5000 app:app # Example Gunicorn command
    ```

## Project Structure

```
.
├── app.py             # Main Flask application file
├── templates/         # HTML templates (Jinja2)
│   ├── home.html
│   ├── login.html
│   ├── problems.html
│   ├── individual-problem.html
│   ├── contests.html
│   ├── individual-contest.html
│   ├── create_announcement.html
│   ├── create_problem.html
│   ├── create_problem_ai.html
│   ├── create_contest.html
│   ├── announcement.html
│   ├── users.html
│   ├── user.html
│   ├── contest-results.html
│   └── ... (other template files)
├── static/            # Static files (CSS, JavaScript, images)
│   ├── css/
│   ├── js/
│   └── img/
├── .env               # Environment variables (ignored by git)
├── requirements.txt   # Python dependencies
└── .gitignore         # Files/directories ignored by git
```

## Key Features & Logic

*   **Authentication (`/api/v1/auth/external/_handler`):** Handles the OAuth2 callback, exchanges the code for user info, finds or creates the user in MongoDB, and sets up the session.
*   **Submission Processing (`/api/v1/submissions`):**
    *   Receives code, problem ID, language.
    *   Checks rate limits.
    *   Performs similarity check (`is_code_similar`) against existing submissions for the *same* problem.
    *   Sends code + stdin + expected output (Base64 encoded) to Judge0 API.
    *   Stores initial submission details (including Judge0 token) in MongoDB.
*   **Submission Result Retrieval (`/api/v1/submissions/<submission_id>`):**
    *   Polls the Judge0 API using the stored token.
    *   Updates the submission status in MongoDB.
    *   Compares actual output with expected output (`compare_output`) if the submission ran successfully.
    *   Updates problem statistics (accepted/rejected counts).
    *   Updates contest leaderboard if applicable (`add_competition_submission`).
*   **Contest Logic (`add_competition_submission`, `calculate_score`):**
    *   Checks if a submission belongs to an active contest and if the user is registered.
    *   Updates the user's entry in the contest leaderboard (attempts, accepted status, fastest accepted submission ID).
    *   Calculates the user's score based on problem difficulty, penalties for incorrect attempts, and submission time bonus.
*   **Leaderboards (`calculate_global_leaderboard`):** Iterates through *ended* contests, aggregates user scores and problems solved to generate a global ranking.
*   **AI Integration:**
    *   `generate_problem_using_ai`: Constructs a detailed prompt for Gemini, requests a unique problem (title, description, stdin, solution, tags, level), executes the generated Python solution against the generated stdin to get the stdout, and returns the formatted problem data.
    *   `generate_contest_report`: Sends contest metadata, submission logs, problem details, and leaderboard data to Gemini to generate HTML-formatted summary and improvement reports.
    *   User Summary Generation: Sends user profile info and submission history snippets to Gemini for a concise summary.
*   **Context Processors (`@app.context_processor`):** Injects frequently needed data (e.g., active announcements, upcoming contests, global leaderboard) into all templates, avoiding repetitive queries in route functions.
*   **Middleware (`@app.after_request`):** Sets appropriate `Cache-Control` and `Content-Type` headers based on the request path.

## API Endpoints

### Frontend Routes

(Accessed via Browser - Return HTML Pages)

*   `GET /`: Homepage.
*   `GET /login`: Displays login prompt, redirects to OAuth provider.
*   `GET /logout`: Clears the session and redirects to login.
*   `GET /users`: (Admin only) Displays list of all users.
*   `GET /users/<user_id>`: Displays a specific user's profile page.
*   `GET /platform-information`: (Admin only) Returns JSON platform statistics (intended for an admin dashboard, currently returns raw JSON).
*   `GET /announcements/<announcement_id>`: Displays a specific announcement.
*   `GET /problems`: Displays list of accessible problems.
*   `GET /problems/<problem_id>`: Displays details of a specific problem and submission interface.
*   `GET /contests`: Displays list of contests.
*   `GET /contests/<contest_id>`: Displays details of a specific contest, including problems and leaderboard (if applicable).
*   `GET /create-announcement`: (Admin only) Page to create a new announcement.
*   `GET /create-problem`: (Admin only) Page to manually create a new problem.
*   `GET /create-problem-ai`: (Admin only) Page to generate a new problem using AI.
*   `GET /create-contest`: (Admin only) Page to create a new contest.
*   `GET /contest-results/<contest_id>`: (Admin only) Displays detailed results and AI-generated report for a finished contest.

### Backend API Routes

(Typically accessed via JavaScript/AJAX - Return JSON)

*   `GET /api/v1/health`: Health check endpoint. Returns `{"response_code": 200, "message": "OK"}`.
*   `GET /api/v1/auth/external/_handler`: Handles OAuth2 callback (**Internal Redirect Target**).
*   `GET /api/v1/user`: (Requires login) Returns current logged-in user's data.
*   `POST /api/v1/user/university-details`: (Requires login) Updates user's university roll number and profile picture. Expects `multipart/form-data`.
*   `POST /api/v1/create-announcement`: (Admin only) Creates a new announcement. Expects `form-data`.
*   `POST /api/v1/announcements/toogle-visibility`: (Admin only) Toggles the active status of an announcement. Expects `form-data` with `announcement_id`.
*   `POST /api/v1/create-problem`: (Admin only) Creates a new problem. Expects `form-data`.
*   `POST /api/v1/submissions`: (Requires login) Creates a new code submission. Expects JSON body: `{"problem_id": "...", "code": "...", "language": "...", "key_strokes": ..., "focus_events": ...}`.
*   `GET /api/v1/submissions/<submission_id>`: (Requires login, user must own submission) Retrieves the status and results of a specific submission from Judge0.
*   `POST /api/v1/create-contest`: (Admin only) Creates a new contest. Expects `form-data`.
*   `POST /api/v1/contest/register/<contest_id>`: (Requires login) Registers the current user for a contest.
*   `GET /api/v1/ai/create-problem`: (Admin only) Generates problem details using AI based on difficulty query parameter (e.g., `/api/v1/ai/create-problem?difficulty=Medium`). Returns JSON.

## Contributing

Contributions are welcome! Please follow these steps:

1.  **Fork** the repository on GitHub.
2.  **Clone** your fork locally: `git clone https://github.com/your-username/a-star-platform.git`
3.  **Create a new branch** for your feature or bug fix: `git checkout -b feature/your-feature-name` or `git checkout -b fix/your-bug-fix`.
4.  **Make your changes.** Ensure code follows general Python best practices.
5.  **Test your changes** thoroughly.
6.  **Commit your changes** with descriptive messages: `git commit -m "feat: Add feature X"` or `git commit -m "fix: Resolve issue Y"`.
7.  **Push** your branch to your fork: `git push origin feature/your-feature-name`.
8.  **Open a Pull Request** on the original repository, detailing your changes.
