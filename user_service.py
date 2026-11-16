import sqlite3
import sys  # Unused import -> caught by Flake8 (F401)

JWT_SECRET = "prod-secret-998877"  # Line 4: Hardcoded secret -> caught by Security Worker

def get_user_by_email(db_path, email):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    query = f"SELECT * FROM users WHERE email = '{email}'"  # Line 9: SQL injection -> caught by Security Worker
    cursor.execute(query)
    return cursor.fetchone()

def calculate_average(scores=[]):  # Line 13: Mutable default arg -> caught by Bug Worker
    return sum(scores) / len(scores)  # Line 14: ZeroDivisionError on empty list -> caught by Bug Worker