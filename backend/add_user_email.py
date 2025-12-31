import psycopg2
import json
import os
import sys

def get_db_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config['database']

def add_authorized_email(email):
    db_config = get_db_config()

    conn = psycopg2.connect(
        host=db_config['host'],
        port=db_config['port'],
        user=db_config['username'],
        password=db_config['password'],
        dbname=db_config['name']
    )

    cursor = conn.cursor()

    try:
        check_query = 'SELECT id, email FROM auth.users WHERE email = %s'
        cursor.execute(check_query, (email,))
        existing = cursor.fetchone()

        if existing:
            print(f"Email {email} already exists in the database.")
            return

        insert_query = '''
            INSERT INTO auth.users (email, role)
            VALUES (%s, %s)
            RETURNING id, email
        '''
        cursor.execute(insert_query, (email, 'general_member'))
        new_user = cursor.fetchone()

        conn.commit()

        print(f"Success! Pre-authorized email added:")
        print(f"  ID: {new_user[0]}")
        print(f"  Email: {new_user[1]}")
        print(f"\nUser can now register at the 'Join the fund' page.")

    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python add_user_email.py <email>")
        print("Example: python add_user_email.py newuser@example.com")
        sys.exit(1)

    email = sys.argv[1]
    add_authorized_email(email)
