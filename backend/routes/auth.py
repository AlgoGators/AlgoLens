from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash, generate_password_hash
from database import execute_query

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()

    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Email and password are required'}), 400

    email = data['email']
    password = data['password']

    query = 'SELECT * FROM auth.users WHERE email = %s'
    user = execute_query(query, (email,), fetch_one=True)

    if not user:
        return jsonify({'error': 'Invalid email or password'}), 401

    if not check_password_hash(user['password'], password):
        return jsonify({'error': 'Invalid email or password'}), 401

    access_token = create_access_token(
        identity=user['id'],
        additional_claims={
            'email': user['email'],
            'role': user.get('role', 'general_member')
        }
    )

    return jsonify({
        'token': access_token,
        'user': {
            'id': user['id'],
            'email': user['email'],
            'first_name': user.get('first_name'),
            'last_name': user.get('last_name'),
            'role': user.get('role', 'general_member')
        }
    }), 200

@auth_bp.route('/verify', methods=['GET'])
def verify():
    from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

    @jwt_required()
    def verify_token():
        current_user_id = get_jwt_identity()
        claims = get_jwt()

        query = 'SELECT * FROM auth.users WHERE id = %s'
        user = execute_query(query, (current_user_id,), fetch_one=True)

        if not user:
            return jsonify({'error': 'User not found'}), 404

        return jsonify({
            'user': {
                'id': user['id'],
                'email': user['email'],
                'first_name': user.get('first_name'),
                'last_name': user.get('last_name'),
                'role': user.get('role', 'general_member')
            }
        }), 200

    return verify_token()

@auth_bp.route('/check-email', methods=['POST'])
def check_email():
    data = request.get_json()

    if not data or not data.get('email'):
        return jsonify({'error': 'Email is required'}), 400

    email = data['email']

    query = 'SELECT id, email, password FROM auth.users WHERE email = %s'
    user = execute_query(query, (email,), fetch_one=True)

    if not user:
        return jsonify({'exists': False, 'message': 'Email not found. Contact an administrator to be added.'}), 404

    has_password = user['password'] is not None and user['password'] != ''

    if has_password:
        return jsonify({'exists': True, 'registered': True, 'message': 'Account already registered. Please login.'}), 200

    return jsonify({'exists': True, 'registered': False, 'message': 'Email found. Please complete registration.'}), 200

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()

    if not data or not data.get('email') or not data.get('password') or not data.get('first_name') or not data.get('last_name'):
        return jsonify({'error': 'Email, password, first name, and last name are required'}), 400

    email = data['email']
    password = data['password']
    first_name = data['first_name']
    last_name = data['last_name']

    check_query = 'SELECT id, password FROM auth.users WHERE email = %s'
    user = execute_query(check_query, (email,), fetch_one=True)

    if not user:
        return jsonify({'error': 'Email not authorized. Contact an administrator.'}), 403

    if user['password'] and user['password'] != '':
        return jsonify({'error': 'Account already registered. Please login.'}), 400

    hashed_password = generate_password_hash(password)

    update_query = '''
        UPDATE auth.users
        SET password = %s, first_name = %s, last_name = %s
        WHERE email = %s
        RETURNING id, email, first_name, last_name, role
    '''

    from database import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(update_query, (hashed_password, first_name, last_name, email))
            updated_user = cursor.fetchone()
            conn.commit()

            access_token = create_access_token(
                identity=updated_user['id'],
                additional_claims={
                    'email': updated_user['email'],
                    'role': updated_user.get('role', 'general_member')
                }
            )

            return jsonify({
                'token': access_token,
                'user': {
                    'id': updated_user['id'],
                    'email': updated_user['email'],
                    'first_name': updated_user.get('first_name'),
                    'last_name': updated_user.get('last_name'),
                    'role': updated_user.get('role', 'general_member')
                }
            }), 201
    finally:
        conn.close()
