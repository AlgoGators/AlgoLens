import psycopg2
from werkzeug.security import generate_password_hash
import json
import os

def get_db_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config['database']

def setup_database():
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
        print("Creating auth schema if it doesn't exist...")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS auth;")

        print("\nDropping existing users table if it exists...")
        cursor.execute("DROP TABLE IF EXISTS auth.users CASCADE;")

        print("Creating users table with correct schema...")
        cursor.execute("""
            CREATE TABLE auth.users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password VARCHAR(255),
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                role VARCHAR(50) DEFAULT 'general_member',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        print("\nInserting test user: dominickdupuy@ufl.edu...")
        hashed_password = generate_password_hash('wasd')

        cursor.execute("""
            INSERT INTO auth.users (email, password, first_name, last_name, role)
            VALUES (%s, %s, %s, %s, %s)
        """, ('dominickdupuy@ufl.edu', hashed_password, 'Dominick', 'Dupuy', 'general_member'))

        conn.commit()

        print("\nDatabase setup complete!")
        print("\nTest user created:")
        print("  Email: dominickdupuy@ufl.edu")
        print("  Password: wasd")
        print("  Name: Dominick Dupuy")

        cursor.execute("SELECT id, email, first_name, last_name, role, created_at FROM auth.users;")
        users = cursor.fetchall()
        print("\nCurrent users in database:")
        for user in users:
            print(f"  ID: {user[0]}, Email: {user[1]}, Name: {user[2]} {user[3]}, Role: {user[4]}, Created: {user[5]}")

    except Exception as e:
        print(f"\nError: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    setup_database()
