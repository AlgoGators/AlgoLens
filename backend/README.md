# Authentication Backend Setup

## Installation

1. Install Python dependencies:
```bash
cd backend
pip install -r requirements.txt
```

2. Set JWT secret key (optional - defaults to a placeholder):
```bash
export JWT_SECRET_KEY="your-secure-secret-key-here"
```

## Database Setup

The database connection is configured in `config.json` at the root of the project.

Make sure your PostgreSQL database has the following schema:

```sql
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE auth.users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    role VARCHAR(50) DEFAULT 'general_member',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Running the Backend

```bash
cd backend
python app.py
```

The server will run on `http://localhost:5000`

## API Endpoints

### POST /auth/login
Login with email and password

Request:
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

Response:
```json
{
  "token": "jwt_token_here",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "role": "general_member"
  }
}
```

### GET /auth/verify
Verify JWT token (requires Authorization header)

Request Headers:
```
Authorization: Bearer <jwt_token>
```

Response:
```json
{
  "user": {
    "id": 1,
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "role": "general_member"
  }
}
```

## Note

Passwords in the database must be hashed using werkzeug.security.generate_password_hash().

Example to create a test user:
```python
from werkzeug.security import generate_password_hash
import psycopg2

conn = psycopg2.connect(
    host="13.58.153.216",
    port="5432",
    user="postgres",
    password="algogators",
    dbname="algo_data"
)

cursor = conn.cursor()
hashed_password = generate_password_hash("your_password")

cursor.execute(
    "INSERT INTO auth.users (email, password, first_name, last_name) VALUES (%s, %s, %s, %s)",
    ("test@example.com", hashed_password, "Test", "User")
)

conn.commit()
conn.close()
```
