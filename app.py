import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, session
import calendar
import sqlite3
import random
import anthropic
from functools import wraps
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import re

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
client = anthropic.Client(api_key=os.getenv("ANTHROPIC_API_KEY"))


def extract_tasks(claude_response):
    """Extract numbered tasks from Claude's response"""
    print("Raw Claude response:", claude_response)  # Debug print

    try:
        # Try to get the content directly if it's in the response
        if isinstance(claude_response, dict) and 'content' in claude_response:
            tasks_text = claude_response['content']
        else:
            tasks_text = str(claude_response)

        print("Tasks text:", tasks_text)  # Debug print

        # Look for tasks between tags or just numbered items if tags aren't found
        tasks_match = re.search(r'<mental_health_tasks>(.*?)</mental_health_tasks>',
                                tasks_text, re.DOTALL)

        if tasks_match:
            tasks_content = tasks_match.group(1).strip()
        else:
            tasks_content = tasks_text

        print("Tasks content:", tasks_content)  # Debug print

        # Try to extract tasks with brackets first
        tasks = re.findall(r'\d+\.\s*\[(.*?)\]', tasks_content)

        # If no bracketed tasks found, try without brackets
        if not tasks:
            tasks = re.findall(r'\d+\.\s*(.*?)(?=(?:\d+\.|$))', tasks_content, re.DOTALL)

        # Clean up the tasks
        tasks = [task.strip() for task in tasks if task.strip()]

        print("Extracted tasks:", tasks)  # Debug print

        return tasks
    except Exception as e:
        print(f"Error extracting tasks: {e}")  # Debug print
        return []


def get_daily_tasks(user_id):
    """Get or generate daily tasks for the user"""
    today = datetime.now().strftime('%Y-%m-%d')

    # Include user_id in the session key to separate tasks per user
    session_key = f'daily_tasks_{user_id}_{today}'

    if session_key in session:
        tasks = session[session_key]
        if tasks:  # Only return if tasks exist
            return tasks

    # If not, generate new tasks
    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()

    c.execute("""SELECT age_range, gender, employment_status, prompt_categories 
                 FROM users WHERE id = ?""", (user_id,))
    user_data = c.fetchone()
    conn.close()

    if user_data:
        user_info = {
            'age_range': user_data[0],
            'gender': user_data[1],
            'employment_status': user_data[2],
            'prompt_categories': user_data[3].split(',') if user_data[3] else []
        }

        print(f"Generating tasks for user {user_id} with info:", user_info)  # Debug print

        # Generate tasks using Claude
        claude_response = generate_personalized_tasks(user_info)
        tasks = extract_tasks(claude_response)

        print(f"Generated tasks for user {user_id}:", tasks)  # Debug print

        if tasks:
            # Store in session with user-specific key
            session[session_key] = tasks
            return tasks
        else:
            print(f"No tasks were generated for user {user_id}")  # Debug print

    return []


def generate_personalized_tasks(user_info):
    """Generate personalized tasks using Claude API"""
    prompt = """You are an AI assistant tasked with generating personalized mental health tasks for users based on their demographic information and selected parameters. Generate exactly 5 specific, actionable tasks that can help boost the user's mental health.

First, review the user's information:

<user_info>
Age: {age_range}
Gender: {gender}
Occupation: {employment_status}
</user_info>

Now, consider the parameters the user has selected as important for their mental health:

<selected_parameters>
{prompt_categories}
</selected_parameters>

Generate exactly 5 mental health tasks that are tailored to the user's profile and selected parameters. Each task should be specific, actionable, and designed to boost mental health.

Your response must follow this exact format:

<mental_health_tasks>
1. [First specific, actionable task]
2. [Second specific, actionable task]
3. [Third specific, actionable task]
4. [Fourth specific, actionable task]
5. [Fifth specific, actionable task]
</mental_health_tasks>"""

    formatted_prompt = prompt.format(
        age_range=user_info['age_range'],
        gender=user_info['gender'],
        employment_status=user_info['employment_status'],
        prompt_categories=', '.join(user_info['prompt_categories'])
    )

    print("Sending prompt to Claude:", formatted_prompt)  # Debug print

    try:
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            temperature=0,
            messages=[{
                "role": "user",
                "content": formatted_prompt
            }]
        )

        return message.content
    except Exception as e:
        print(f"Error calling Claude API: {e}")  # Debug print
        return None


# Database initialization
def init_db():
    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()

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


@app.route('/generate_tasks')
@login_required
def generate_tasks():
    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()

    # Fetch user information
    c.execute("""SELECT age_range, gender, employment_status, prompt_categories 
                 FROM users WHERE id = ?""", (session['user_id'],))
    user_data = c.fetchone()
    conn.close()

    if user_data:
        user_info = {
            'age_range': user_data[0],
            'gender': user_data[1],
            'employment_status': user_data[2],
            'prompt_categories': user_data[3].split(',') if user_data[3] else []
        }

        # Generate personalized tasks using Claude
        tasks = generate_personalized_tasks(user_info)

        return render_template('personalized_tasks.html', tasks=tasks)

    flash('Unable to generate personalized tasks. Please complete your profile.')
    return redirect(url_for('dashboard'))

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


PROMPT_CATEGORIES = {
    "Nutrition": "Eat a red fruit today.",
    "Exercise": "Do 20 jumping jacks.",
    "Intellectual": "Recommend a news article.",
    "Environment": "Go on a 5-minute walk outside, or watch the sunset.",
    "Emotional": "Look into the mirror and tell yourself 'You got this!'"
}
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

    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()

    # Check if an entry already exists for today; if so, update it, otherwise insert a new entry
    c.execute("""SELECT id FROM journal_entries WHERE user_id = ? AND date = ?""",
              (session['user_id'], today))
    existing_entry = c.fetchone()

    if existing_entry:
        # Update existing entry
        c.execute("""UPDATE journal_entries SET entry = ? WHERE id = ?""",
                  (journal_entry, existing_entry[0]))
    else:
        # Insert new entry
        c.execute("""INSERT INTO journal_entries (user_id, date, entry) VALUES (?, ?, ?)""",
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

    # Get today's tasks
    tasks = get_daily_tasks(session['user_id'])
    print("Tasks for dashboard:", tasks)  # Debug print

    # Get responses from database
    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()
    c.execute("""SELECT prompt_number, response 
                 FROM responses 
                 WHERE user_id = ? AND date = ?""",
              (session['user_id'], today))
    responses = dict(c.fetchall())
    conn.close()

    # Combine tasks with their responses
    prompts_and_responses = []
    for i, task in enumerate(tasks, 1):
        response = responses.get(i, '')
        prompts_and_responses.append((i, task, response))

    print("Final prompts and responses:", prompts_and_responses)  # Debug print

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

    # Check if a response already exists
    c.execute("""SELECT id FROM responses 
                 WHERE user_id = ? AND date = ? AND prompt_number = ?""",
              (session['user_id'], today, prompt_number))
    existing = c.fetchone()

    if existing:
        if response:  # If marking as complete
            c.execute("""UPDATE responses 
                        SET response = ? 
                        WHERE user_id = ? AND date = ? AND prompt_number = ?""",
                      (response, session['user_id'], today, prompt_number))
        else:  # If unmarking/removing completion
            c.execute("""DELETE FROM responses 
                        WHERE user_id = ? AND date = ? AND prompt_number = ?""",
                      (session['user_id'], today, prompt_number))
    else:
        if response:  # Only insert if marking as complete
            c.execute("""INSERT INTO responses (user_id, date, prompt_number, response)
                        VALUES (?, ?, ?, ?)""",
                      (session['user_id'], today, prompt_number, response))

    conn.commit()
    conn.close()

    return redirect(url_for('dashboard'))




@app.route('/view_journal')
@login_required
def view_journal():
    print("hellofds")
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))

    # Get calendar information
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]

    # Get previous and next month links
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    # Get response data for the month
    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()

    # Format dates properly for SQLite comparison
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month + 1:02d}-01" if month < 12 else f"{year + 1}-01-01"

    c.execute("""
        SELECT date, 
               COUNT(DISTINCT journal_entries.id) AS entry_count,
               journal_entries.entry AS journal_entry
        FROM journal_entries
        JOIN users ON users.id = journal_entries.user_id
        WHERE users.id = ? 
          AND date >= ? 
          AND date < ?
        GROUP BY date
    """, (session['user_id'], start_date, end_date))

    rows = c.fetchall()
    print(rows)

    # Print each row in the table
    for row in rows:
        print("SDKJf")
        print(row)
    print("\n" + "-" * 40 + "\n")  # Separator between tables

    # Create a dictionary of dates with response counts and journal entries
    response_data = {}
    for row in rows:
        date = row[0]
        response_data[date] = {
            'journal_entry': row[2] if row[2] else None
        }

    conn.close()

    return render_template('view_journal.html',
                           calendar=cal,
                           month_name=month_name,
                           year=year,
                           month=month,
                           prev_month=prev_month,
                           prev_year=prev_year,
                           next_month=next_month,
                           next_year=next_year,
                           response_data=response_data,
                           current_date=datetime.now().strftime('%Y-%m-%d'))
# Logout route
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
