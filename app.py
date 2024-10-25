from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
import sqlite3
import random
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a secure secret key


# Database initialization
def init_db():
    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS responses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  date TEXT,
                  prompt_number INTEGER,
                  response TEXT,
                  FOREIGN KEY (user_id) REFERENCES users (id))''')
    conn.commit()
    conn.close()


# Mental health prompts
DAILY_PROMPTS = [
    "How would you rate your mood today from 1-10? What influenced this rating?",
    "What's one thing you're grateful for today?",
    "What's one challenge you faced today and how did you handle it?",
    "Name one act of self-care you practiced today.",
    "What's one goal you'd like to accomplish tomorrow?"
]


# Login required decorator
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


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']  # In production, hash this password

        conn = sqlite3.connect('daily_tallies.db')
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                      (username, password))
            conn.commit()
            flash('Registration successful! Please login.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already exists!')
        finally:
            conn.close()
    return render_template('register.html')


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


@app.route('/dashboard')
@login_required
def dashboard():
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()

    # Get today's responses
    c.execute("""SELECT prompt_number, response 
                 FROM responses 
                 WHERE user_id = ? AND date = ?""",
              (session['user_id'], today))
    responses = dict(c.fetchall())
    conn.close()

    # Create prompt-response pairs
    prompts_and_responses = []
    for i, prompt in enumerate(DAILY_PROMPTS, 1):
        response = responses.get(i, '')
        prompts_and_responses.append((i, prompt, response))

    return render_template('dashboard.html',
                           prompts_and_responses=prompts_and_responses,
                           date=today)


@app.route('/submit_response', methods=['POST'])
@login_required
def submit_response():
    prompt_number = int(request.form['prompt_number'])
    response = request.form['response']
    today = datetime.now().strftime('%Y-%m-%d')

    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()

    # Check if response exists and update, or create new
    c.execute("""INSERT OR REPLACE INTO responses 
                 (user_id, date, prompt_number, response)
                 VALUES (?, ?, ?, ?)""",
              (session['user_id'], today, prompt_number, response))
    conn.commit()
    conn.close()

    flash('Response saved successfully!')
    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))


with app.app_context():
    init_db()

# ... (rest of your routes and code)

if __name__ == '__main__':
    app.run(debug=True)