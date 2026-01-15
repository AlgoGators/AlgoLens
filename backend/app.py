from flask import Flask, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
import os
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=ENV_PATH)

# Determine environment
ENV = os.getenv('FLASK_ENV', 'production')
DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

app = Flask(__name__)

# Configure CORS securely
if ENV == 'production':
    CORS(
        app,
        supports_credentials=True,
        resources={r"/*": {"origins": os.getenv("CORS_ORIGINS", "*").split(",")}}
    )
else:
    # Development: allow everything
    CORS(app, supports_credentials=True)

# Configure logging
if not app.debug:
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.mkdir('logs')

    # File handler for all logs
    file_handler = RotatingFileHandler('logs/algolens.log', maxBytes=10240000, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)

# Console handler for immediate debugging
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s'
))
console_handler.setLevel(logging.DEBUG)
app.logger.addHandler(console_handler)

app.logger.setLevel(logging.DEBUG)
app.logger.info('AlgoLens backend startup')

# Log all requests
@app.before_request
def log_request_info():
    app.logger.info('Request: %s %s from %s', request.method, request.path, request.remote_addr)
    if request.get_json(silent=True):
        # Log request body but mask sensitive fields
        data = request.get_json()
        safe_data = {k: ('***' if k in ['password'] else v) for k, v in data.items()}
        app.logger.debug('Request body: %s', safe_data)

@app.after_request
def log_response_info(response):
    app.logger.info('Response: %s %s - Status %s', request.method, request.path, response.status_code)

    # CORS debugging for production issues
    origin = request.headers.get('Origin')
    if origin:
        app.logger.info('[CORS] Request Origin: %s', origin)
        app.logger.info('[CORS] Response Access-Control-Allow-Origin: %s',
                       response.headers.get('Access-Control-Allow-Origin', 'NOT SET'))

        # Check if CORS headers are missing on error responses
        if response.status_code >= 400 and not response.headers.get('Access-Control-Allow-Origin'):
            app.logger.warning('[CORS] WARNING: Error response missing CORS headers - browser may not show error details')

    return response

# Handle preflight requests explicitly for debugging
@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        app.logger.info('[CORS] Preflight request from Origin: %s', request.headers.get('Origin'))
        app.logger.info('[CORS] Access-Control-Request-Method: %s', request.headers.get('Access-Control-Request-Method'))
        app.logger.info('[CORS] Access-Control-Request-Headers: %s', request.headers.get('Access-Control-Request-Headers'))

app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = 43200

jwt = JWTManager(app)

from routes.auth import auth_bp
from routes.portfolio import portfolio_bp
from database import get_db_connection

app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(portfolio_bp, url_prefix='/portfolio')

# Health check endpoint for debugging connectivity
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint - no auth required. Use for debugging connectivity."""
    app.logger.info('[HEALTH] Health check called')

    health_status = {
        'status': 'ok',
        'environment': ENV,
        'debug': DEBUG,
        'cors_origins': os.getenv('CORS_ORIGINS', '*'),
        'checks': {}
    }

    # Test database connection
    try:
        app.logger.info('[HEALTH] Testing database connection...')
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('SELECT 1')
            result = cursor.fetchone()
        conn.close()
        health_status['checks']['database'] = 'ok'
        app.logger.info('[HEALTH] Database connection successful')
    except Exception as e:
        health_status['checks']['database'] = f'error: {str(e)}'
        health_status['status'] = 'degraded'
        app.logger.error(f'[HEALTH] Database connection failed: {str(e)}', exc_info=True)

    app.logger.info(f'[HEALTH] Health check result: {health_status}')
    return health_status, 200 if health_status['status'] == 'ok' else 503

if __name__ == '__main__':
    # NEVER use debug=True in production - it exposes remote code execution vulnerability
    port = int(os.getenv('PORT', 5000))
    app.run(debug=DEBUG, port=port, host='0.0.0.0')
