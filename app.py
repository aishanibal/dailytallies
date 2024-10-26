import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a secure secret key

# Define prompt categories with example prompts
PROMPT_CATEGORIES = {
    "Nutrition": "Eat a red fruit today.",
    "Exercise": "Do 20 jumping jacks.",
    "Intellectual": "Recommend a news article.",
    "Environment": "Go on a 5-minute walk outside, or watch the sunset.",
    "Emotional": "Look into the mirror and tell yourself 'You got this!'"
}

# Database initialization
def init_db():
    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()


    # Example: view all data in the users table
    #c.execute("SELECT * FROM users")
    #rows = c.fetchall()

    #for row in rows:
      #  print(row)



    # Create users and responses tables if they don't exist
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL,
                  age_range TEXT,
                  gender TEXT,
                  employment_status TEXT,
                  prompt_categories TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS responses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  date TEXT,
                  prompt_number INTEGER,
                  response TEXT,
                  FOREIGN KEY (user_id) REFERENCES users (id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS journal_entries
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      date TEXT,
                      entry TEXT,
                      FOREIGN KEY (user_id) REFERENCES users (id))''')
    # Other initialization code...

    conn.commit()
    conn.close()


# Run database initialization
with app.app_context():
    init_db()

# Decorator to enforce login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']  # In production, hash this password
        age_range = request.form['age_range']
        gender = request.form['gender']
        employment_status = request.form['employment_status']
        selected_categories = request.form.getlist('prompt_categories')
        prompt_categories = ",".join(selected_categories)  # Store as comma-separated string

        conn = sqlite3.connect('daily_tallies.db')
        c = conn.cursor()
        try:
            c.execute("""INSERT INTO users (username, password, age_range, gender, employment_status, prompt_categories) 
                         VALUES (?, ?, ?, ?, ?, ?)""",
                      (username, password, age_range, gender, employment_status, prompt_categories))
            conn.commit()
            flash('Registration successful! Please login.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already exists!')
        finally:
            conn.close()
    return render_template('register.html', prompt_categories=PROMPT_CATEGORIES)

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect('daily_tallies.db')
        c = conn.cursor()
        c.execute("SELECT id, password FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()

        if user and user[1] == password:  # In production, verify hashed password
            session['user_id'] = user[0]
            return redirect(url_for('dashboard'))
        flash('Invalid username or password!')
    return render_template('login.html')


# Journal Page Route
@app.route('/journal', methods=['GET'])
@login_required
def journal():
    return render_template('journal.html')

# Submit Journal Entry Route
@app.route('/submit_journal', methods=['POST'])
@login_required
def submit_journal():
    journal_entry = request.form['journal_entry']
    today = datetime.now().strftime('%Y-%m-%d')

    # Store the journal entry in the database (assuming a 'journal_entries' table exists)
    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()
    c.execute("""INSERT INTO journal_entries (user_id, date, entry)
                 VALUES (?, ?, ?)""",
              (session['user_id'], today, journal_entry))
    conn.commit()
    conn.close()

    flash('Journal entry saved successfully!')
    return redirect(url_for('journal'))

# Make sure the database table for journal entries exists


# Dashboard route
@app.route('/dashboard')
@login_required
def dashboard():
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()

    # Retrieve user's selected categories
    c.execute("SELECT prompt_categories FROM users WHERE id = ?", (session['user_id'],))
    user_categories = c.fetchone()[0]
    if user_categories:
        user_categories = user_categories.split(',')
    else:
        user_categories = []

    # Get today's responses
    c.execute("""SELECT prompt_number, response 
                 FROM responses 
                 WHERE user_id = ? AND date = ?""",
              (session['user_id'], today))
    responses = dict(c.fetchall())
    conn.close()

    # Filter prompts based on user-selected categories
    prompts_and_responses = []
    for i, (category, prompt) in enumerate(PROMPT_CATEGORIES.items(), 1):
        if category in user_categories:
            response = responses.get(i, '')
            prompts_and_responses.append((i, prompt, response))

    return render_template('dashboard.html',
                           prompts_and_responses=prompts_and_responses,
                           date=today)

# Submit response route
@app.route('/submit_response', methods=['POST'])
@login_required
def submit_response():
    prompt_number = int(request.form['prompt_number'])
    response = request.form['response']
    today = datetime.now().strftime('%Y-%m-%d')

    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()

    # Insert or update the response
    c.execute("""INSERT OR REPLACE INTO responses 
                 (user_id, date, prompt_number, response)
                 VALUES (?, ?, ?, ?)""",
              (session['user_id'], today, prompt_number, response))
    conn.commit()
    conn.close()

    flash('Response saved successfully!')
    return redirect(url_for('dashboard'))

# Logout route
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
