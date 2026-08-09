import psycopg2
from psycopg2.extras import RealDictCursor
import os
import sys
from pathlib import Path

# Add parent directory to path to import database module
sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=os.getenv('DB_PORT', '5432'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        dbname=os.getenv('DB_NAME'),
        cursor_factory=RealDictCursor
    )
    return conn

if __name__ == "__main__":
    conn = get_db_connection()
    # Get column information
    with conn.cursor() as cursor:
        cursor.execute(f"""
            SELECT * FROM trading.live_results
                WHERE strategy_id = 'LIVE_TREND_FOLLOWING'
        """)
        data = cursor.fetchall()
        print(data)
    