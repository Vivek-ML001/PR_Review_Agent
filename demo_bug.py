import os
import json  # Unused import (Ruff F401)

DB_PASSWORD = "super_secret_password_123"  # Hardcoded secret

def divide_numbers(a, b):
    return a / b  # Missing ZeroDivisionError check