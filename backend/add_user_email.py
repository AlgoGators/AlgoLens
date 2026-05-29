import psycopg2
import os
import sys
from dotenv import load_dotenv

load_dotenv()

def add_authorized_email(email, reset=False):
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=os.getenv('DB_PORT', '5432'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        dbname=os.getenv('DB_NAME')
    )

    cursor = conn.cursor()

    try:
        check_query = 'SELECT id, email FROM auth.users WHERE email = %s'
        cursor.execute(check_query, (email,))
        existing = cursor.fetchone()

        if existing:
            if not reset:
                print(f"Email {email} already exists in the database.")
                return
            else:
                # Reset: delete existing record
                delete_query = 'DELETE FROM auth.users WHERE email = %s'
                cursor.execute(delete_query, (email,))
                conn.commit()
                print(f"Deleted existing record for {email}")

        insert_query = '''
            INSERT INTO auth.users (email, password_hash, first_name, last_name, role)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, email
        '''
        cursor.execute(insert_query, (email, '', '', '', 'general_member'))
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
        print("Usage: python add_user_email.py <email> [--reset]")
        print("Example: python add_user_email.py newuser@example.com")
        print("Example with reset: python add_user_email.py newuser@example.com --reset")
        sys.exit(1)

    email = sys.argv[1]
    reset = '--reset' in sys.argv
    add_authorized_email(email, reset=reset)
