from sqlalchemy import create_engine, text
from backend.database import DATABASE_URL

def migrate():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE rate_breakdowns ADD COLUMN source_reference VARCHAR"))
            print("Successfully added source_reference column to rate_breakdowns table")
        except Exception as e:
            print(f"Migration failed (might already exist): {e}")

if __name__ == "__main__":
    migrate()
