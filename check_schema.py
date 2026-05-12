"""
Check Database Schema
"""
import sqlite3

conn = sqlite3.connect('construction_data.db')
cursor = conn.cursor()

# Check sessions table
print("SESSIONS TABLE:")
cursor.execute("PRAGMA table_info(sessions)")
for row in cursor.fetchall():
    print(f"  {row[1]} ({row[2]})")

print("\nCHAT_MESSAGES TABLE:")
cursor.execute("PRAGMA table_info(chat_messages)")
for row in cursor.fetchall():
    print(f"  {row[1]} ({row[2]})")

print("\nPROJECTS TABLE:")
cursor.execute("PRAGMA table_info(projects)")
for row in cursor.fetchall():
    print(f"  {row[1]} ({row[2]})")

conn.close()
