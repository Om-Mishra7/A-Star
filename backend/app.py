import os
import uuid
import requests
from datetime import datetime
import redis
from dotenv import load_dotenv
from pymongo import MongoClient
from flask import Flask, request, jsonify, session, redirect, url_for
from flask_session import Session

from helpers import setup_mongodb


load_dotenv() # take environment variables from .env.

app = Flask(__name__)

# App Configuration
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'session:'
app.config['SESSION_REDIS'] = redis.from_url(os.getenv('REDIS_URI'))
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

Session(app)


# Connect to MongoDB
mongodb_client = MongoClient(os.getenv('MONGODB_URI'))["communitycompetitionprod"]

setup_mongodb(mongodb_client)


# Maintainance endpoints

@app.route('/api/v1/health', methods=['GET'])
def health():
    return jsonify({'response_code': 200, 'message': 'OK', 'identifier': str(uuid.uuid4())})

# Auth endpoints
@app.route('/api/v1/auth/authenticate', methods=['GET'])
def authenticate():
    if session.get('is_authenticated'):
        return jsonify({'response_code': 200, 'data': session['user']['user_account']['user_id'], 'identifier': str(uuid.uuid4())})
    return redirect(f"https://login.microsoftonline.com/{os.getenv('TENANT_ID')}/oauth2/v2.0/authorize"
                    f"?client_id={os.getenv('CLIENT_ID')}"
                    f"&response_type=code"
                    f"&redirect_uri={os.getenv('REDIRECT_URI')}"
                    f"&response_mode=query"
                    f"&scope=openid profile email User.Read") 


@app.route('/api/v1/auth/external/_handler', methods=['GET'])
def external_handler():
    code = request.args.get('code')
    
    # Exchange authorization code for access token
    token_url = f"https://login.microsoftonline.com/{os.getenv('TENANT_ID')}/oauth2/v2.0/token"
    payload = {
        'client_id': os.getenv('CLIENT_ID'),
        'scope': 'openid profile email',
        'code': code,
        'redirect_uri': os.getenv('REDIRECT_URI'),
        'grant_type': 'authorization_code',
        'client_secret': os.getenv('CLIENT_SECRET')
    }

    token_response = requests.post(token_url, data=payload)
    token_data = token_response.json()

    if 'access_token' not in token_data:
        return jsonify({'response_code': 400, 'message': 'Token exchange failed', 'identifier': str(uuid.uuid4())}), 400

    access_token = token_data['access_token']

    # Use the access token to call Microsoft Graph API
    user_info_response = requests.get("https://graph.microsoft.com/v1.0/me", headers={'Authorization': f"Bearer {access_token}", 'Content-Type': 'application/json'})

    if user_info_response.status_code != 200:
        return jsonify({'response_code': 400, 'message': 'Failed to get user info', 'identifier': str(uuid.uuid4())}), 400
    
    user_info = user_info_response.json()

    user_given_name = user_info.get('givenName', 'Unknown')
    primary_email = user_info.get('mail').lower().strip() if 'mail' in user_info else None

    if primary_email is None:
        return jsonify({'response_code': 400, 'message': 'Primary email not found', 'identifier': str(uuid.uuid4())}), 400

    # MongoDB user query and update
    now = datetime.utcnow()  # Current timestamp for created_at and last_logged_in_at

    # Update user details or insert if not exists
    update_result = mongodb_client.users.update_one(
        {'user_account.primary_email': primary_email},
        {
            '$set': {
                'user_account.last_logged_in_at': now  # Update last_logged_in_at for every login
            },
            '$setOnInsert': {
                'user_account.primary_email': primary_email.lower().strip(),
                'user_profile.display_name': user_given_name.title().strip(),
                'user_profile.avatar_url': f'https://api.dicebear.com/9.x/notionists/svg?seed={user_info.get("givenName", "User").title()}',
                'user_account.user_id': str(uuid.uuid4()),
                'user_account.role': 'user',
                'user_account.created_at': now,  # Set created_at only on insert
                'user_account.is_active': True,

            }
        },
        upsert=True 
    )

    if update_result.acknowledged:
        session['is_authenticated'] = True
        session['user'] = mongodb_client.users.find_one({'user_account.primary_email': primary_email}, {'_id': 0})
        return jsonify({'response_code': 200, 'data': session['user']['user_account']['user_id'], 'identifier': str(uuid.uuid4())})
    
    return jsonify({'response_code': 400, 'message': 'Failed to update user info', 'identifier': str(uuid.uuid4())}), 400

    
# User endpoints

@app.route('/api/v1/user', methods=['POST'])
def create_user():
    if session.get('is_authenticated'):
        return jsonify({'response_code': 200, 'data': session['user'], 'identifier': str(uuid.uuid4())})
    return jsonify({'response_code': 401, 'message': 'Unauthorized', 'identifier': str(uuid.uuid4())}), 401




if __name__ == '__main__':
    app.run(debug=True, port=8080)