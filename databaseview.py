import sqlite3

# Connect to your database
conn = sqlite3.connect('daily_tallies.db')
cursor = conn.cursor()

# Example: view all data in the users table
cursor.execute("SELECT * FROM users")
rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()
