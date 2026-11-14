import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATABASE_PATH = PROJECT_ROOT / "data" / "league.db"


def get_connection():
    """
    Create and return a connection to the league database
    """
