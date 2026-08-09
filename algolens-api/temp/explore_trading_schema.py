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

def explore_table_structure(table_name):
    """Get column information for a table"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Get column information
            cursor.execute(f"""
                SELECT column_name, data_type, character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = 'trading' AND table_name = '{table_name}'
                ORDER BY ordinal_position;
            """)
            columns = cursor.fetchall()

            print(f"\n{'='*80}")
            print(f"Table: trading.{table_name}")
            print(f"{'='*80}")
            print(f"{'Column':<40} {'Type':<25} {'Max Length':<15}")
            print(f"{'-'*80}")
            for col in columns:
                max_len = col['character_maximum_length'] or 'N/A'
                print(f"{col['column_name']:<40} {col['data_type']:<25} {str(max_len):<15}")

            # Get sample data
            cursor.execute(f"SELECT * FROM trading.{table_name} LIMIT 5;")
            sample_data = cursor.fetchall()

            print(f"\nSample Data (first 5 rows):")
            print(f"{'-'*80}")
            if sample_data:
                for i, row in enumerate(sample_data):
                    print(f"\nRow {i+1}:")
                    for key, value in row.items():
                        print(f"  {key}: {value}")
            else:
                print("No data found in table")

            # Get row count
            cursor.execute(f"SELECT COUNT(*) as count FROM trading.{table_name};")
            count = cursor.fetchone()['count']
            print(f"\nTotal rows: {count}")

    finally:
        conn.close()

if __name__ == '__main__':
    tables = [
        'equity_curve',
        'executions',
        'live_results',
        'positions',
        'signals',
        'strategy_trading_days_metadata'
    ]

    print("\nExploring Trading Schema Tables")
    print(f"{'='*80}\n")

    for table in tables:
        try:
            explore_table_structure(table)
        except Exception as e:
            print(f"\nError exploring {table}: {str(e)}")

    print(f"\n{'='*80}")
    print("Exploration complete!")
    print(f"{'='*80}\n")
