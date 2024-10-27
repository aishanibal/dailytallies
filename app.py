import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, session
import calendar
import sqlite3
from flask import send_file
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import io
from werkzeug.security import generate_password_hash, check_password_hash
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
        tasks = [task.replace('\\n', '').strip() for task in tasks if task.strip()]

        print("Extracted tasks:", tasks)  # Debug print

        return tasks
    except Exception as e:
        print(f"Error extracting tasks: {e}")  # Debug print
        return []


def get_daily_tasks(user_id):
    """Retrieve today's tasks from the session, or use the next day's tasks if available."""
    today = datetime.now().strftime('%Y-%m-%d')
    session_key = f'daily_tasks_{user_id}_{today}'

    # Check if today's tasks are already in the session
    if session_key not in session:
        # Look for tasks stored as the next day’s tasks from yesterday
        next_day_key = f'daily_tasks_{user_id}_{today}'

        if next_day_key in session:
            # Load next day's tasks for today and clear the next day key
            session[session_key] = session.pop(next_day_key)
            print("Loaded tasks from next day key for today:", session[session_key])  # Debug print
        else:
            # If no next day's tasks are available, request initial tasks from Claude
            conn = sqlite3.connect('daily_tallies.db')
            c = conn.cursor()

            # Retrieve user information for task generation
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

                # Generate initial tasks using Claude
                claude_response = generate_personalized_tasks(user_info)
                tasks = extract_tasks(claude_response)

                if tasks:
                    # Store generated tasks in session for today
                    session[session_key] = tasks
                    print("Initial tasks generated by Claude for today:", session[session_key])  # Debug print
                else:
                    print("Error: No tasks could be generated by Claude.")  # Debug print
                    session[session_key] = []  # Store an empty list or handle as needed
            else:
                print("Error: No user data available to generate tasks.")  # Debug print
                session[session_key] = []  # Handle the case if no user data

    # Retrieve tasks from today's session key to display on the dashboard
    tasks = session[session_key]
    print("Tasks retrieved for today in get_daily_tasks:", tasks)  # Debug print
    return tasks



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
TThese prompts should less than 10 words, and avoid extreme specificity in the prompts.
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

    # Execute and fetch query results
    #c.execute("SELECT * FROM users")
    #rows = c.fetchall()

    #for row in rows:
    #    print(row)

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
                  completed BOOLEAN DEFAULT 0,
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
    "Fitness": "Do 20 jumping jacks.",
    "Knowledge": "Recommend a news article.",
    "Environment": "Go on a 5-minute walk outside, or watch the sunset.",
    "Emotional": "Look into the mirror and tell yourself 'You got this!'"
}
# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        age_range = request.form['age_range']
        gender = request.form['gender']
        employment_status = request.form['employment_status']
        selected_categories = request.form.getlist('prompt_categories')
        prompt_categories = ",".join(selected_categories)  # Store as comma-separated string

        # Validate password length
        if len(password) < 8:
            flash('Password must be at least 8 characters long!')
            return redirect(url_for('register'))

        # Hash the password
        hashed_password = generate_password_hash(password)

        conn = sqlite3.connect('daily_tallies.db')
        c = conn.cursor()
        try:
            # Insert user data including hashed password
            c.execute("""INSERT INTO users (username, password, age_range, gender, employment_status, prompt_categories)
                         VALUES (?, ?, ?, ?, ?, ?)""",
                      (username, hashed_password, age_range, gender, employment_status, prompt_categories))
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
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):  # Adjust index for the 'password' column
            session['user_id'] = user[0]
            flash('Login successful!')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password!')

    return render_template('login.html')


# Journal Page Route
@app.route('/journal', methods=['GET'])
@login_required
def journal():
    today = datetime.now().strftime('%Y-%m-%d')

    # Fetch the journal entry for today, if it exists
    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()
    c.execute("""SELECT entry FROM journal_entries WHERE user_id = ? AND date = ?""",
              (session['user_id'], today))
    journal_entry = c.fetchone()
    conn.close()

    # If a journal entry exists, get the entry text; otherwise, set it to an empty string
    entry_text = journal_entry[0] if journal_entry else ""

    return render_template('journal.html', entry_text=entry_text)

# Submit Journal Entry Route
# Submit Journal Entry Route
@app.route('/submit_journal', methods=['POST'])
@login_required
def submit_journal():
    journal_entry = request.form['journal_entry']
    today = datetime.now().strftime('%Y-%m-%d')
    next_day = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    next_day_session_key = f'daily_tasks_{session["user_id"]}_{next_day}'

    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()

    # Save or update the journal entry
    c.execute("""SELECT id FROM journal_entries WHERE user_id = ? AND date = ?""",
              (session['user_id'], today))
    existing_entry = c.fetchone()

    if existing_entry:
        c.execute("""UPDATE journal_entries SET entry = ? WHERE id = ?""",
                  (journal_entry, existing_entry[0]))
    else:
        c.execute("""INSERT INTO journal_entries (user_id, date, entry) VALUES (?, ?, ?)""",
                  (session['user_id'], today, journal_entry))

    conn.commit()

    # Check which tasks have been completed
    c.execute("""SELECT prompt_number, response FROM responses 
                 WHERE user_id = ? AND date = ? AND response != ''""",
              (session['user_id'], today))
    completed_tasks = [row[1] for row in c.fetchall()]

    if completed_tasks:
        # Fetch user data for prompt categories
        c.execute("""SELECT age_range, gender, employment_status, prompt_categories
                     FROM users WHERE id = ?""", (session['user_id'],))
        user_data = c.fetchone()

        user_info = {
            'age_range': user_data[0],
            'gender': user_data[1],
            'employment_status': user_data[2],
            'prompt_categories': user_data[3].split(',') if user_data[3] else []
        }

        # Prepare Claude prompt with journal entry and completed tasks
        claude_prompt = f"""
        You are an AI assistant generating mental health tasks for users based on their profile and recent activities.

        User Information:
        Age: {user_info['age_range']}
        Gender: {user_info['gender']}
        Occupation: {user_info['employment_status']}
        Selected Parameters: {', '.join(user_info['prompt_categories'])}

        The user has completed the following tasks:
        {', '.join(completed_tasks)}

        Additionally, here is their latest journal entry:
        "{journal_entry}"

        Based on this information, generate exactly 5 new mental health tasks that are specific, actionable, and designed to help the user continue their mental health journey.
        These prompts should less than 10 words, and avoid extreme specificity in the prompts. 

        Your response must follow this exact format:

        <mental_health_tasks>
        1. [First specific, actionable task]
        2. [Second specific, actionable task]
        3. [Third specific, actionable task]
        4. [Fourth specific, actionable task]
        5. [Fifth specific, actionable task]
        </mental_health_tasks>
        """

        print("Sending combined prompt to Claude:", claude_prompt)  # Debug print

        # Generate a new set of tasks
        claude_response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            temperature=0,
            messages=[{
                "role": "user",
                "content": claude_prompt
            }]
        )
        new_tasks = extract_tasks(claude_response)

        if new_tasks:
            # Store new tasks for the next day in session
            session[next_day_session_key] = new_tasks
            print("Next day's tasks set in session:", session[next_day_session_key])  # Debug print

    conn.close()

    return redirect(url_for('dashboard'))

def get_journal_entries(user_id):
    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()

    # Query to fetch journal entries for a specific user
    c.execute("SELECT date, entry FROM journal_entries WHERE user_id = ?", (session['user_id'],))
    entries = c.fetchall()

    # Format the entries for the PDF
    journal_entries = [{'date': entry[0], 'content': entry[1]} for entry in entries]

    conn.close()
    return journal_entries

# Make sure the database table for journal entries exists
def generate_pdf(entries):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    pdf.setTitle("Journal Entries")

    # Title Page
    pdf.setFont("Times-Roman", 24)
    pdf.drawString(100, height - 50, "Journal Entries")
    pdf.setFont("Times-Roman", 12)
    pdf.drawString(100, height - 80, "A compilation of your journal entries.")
    pdf.drawString(100, height - 100, "----------------------------------------")

    # Set font for entries
    pdf.setFont("Times-Roman", 12)

    # Define starting position
    y_position = height - 120

    for entry in entries:
        # Entry Header
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, f"Date: {entry['date']}")
        y_position -= 15  # Space between date and content

        # Entry Content
        pdf.setFont("Times-Roman", 12)
        pdf.drawString(100, y_position, entry['content'])
        y_position -= 30  # Space after the entry content

        # Draw a line to separate entries
        pdf.line(50, y_position, width - 50, y_position)
        y_position -= 30  # Additional space after line

        # Check if we need a new page
        if y_position < 40:
            pdf.showPage()
            pdf.setFont("Times-Roman", 12)
            y_position = height - 40  # Reset y_position for new page

    # Finalize the PDF
    pdf.save()
    buffer.seek(0)
    return buffer
@app.route('/export_journal', methods=['GET'])
def export_journal():
    user_id = request.args.get(session['user_id'])  # Get user ID from request parameters
    entries = get_journal_entries(session['user_id'])
    pdf_buffer = generate_pdf(entries)

    return send_file(pdf_buffer, as_attachment=True, download_name='journal_entries.pdf', mimetype='application/pdf')
# Dashboard route

@app.route('/dashboard')
@login_required
def dashboard():
    today = datetime.now().strftime('%Y-%m-%d')

    # Get today's tasks from the session
    tasks = get_daily_tasks(session['user_id'])
    print("Tasks displayed on dashboard:", tasks)  # Debug print

    # Get responses from the database
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

    print("Final prompts and responses for dashboard:", prompts_and_responses)  # Debug print

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
                        SET response = ?, completed = 1
                        WHERE user_id = ? AND date = ? AND prompt_number = ?""",
                      (response, session['user_id'], today, prompt_number))
        else:  # If unmarking/removing completion
            c.execute("""DELETE FROM responses
                        WHERE user_id = ? AND date = ? AND prompt_number = ?""",
                      (session['user_id'], today, prompt_number))
    else:
        if response:  # Only insert if marking as complete
            c.execute("""INSERT INTO responses (user_id, date, prompt_number, response, completed)
                        VALUES (?, ?, ?, ?, 1)""",
                      (session['user_id'], today, prompt_number, response))

    conn.commit()
    conn.close()

    return redirect(url_for('dashboard'))


@app.route('/view_journal')
@login_required
def view_journal():
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

    # Format dates properly for SQLite comparison
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month + 1:02d}-01" if month < 12 else f"{year + 1}-01-01"

    conn = sqlite3.connect('daily_tallies.db')
    c = conn.cursor()

    # Get journal entries
    c.execute("""
        SELECT date, entry
        FROM journal_entries
        WHERE user_id = ? AND date >= ? AND date < ?
    """, (session['user_id'], start_date, end_date))

    journal_entries = c.fetchall()

    # Get completed responses for the month
    c.execute("""
        SELECT date, prompt_number, response
        FROM responses
        WHERE user_id = ? AND date >= ? AND date < ? AND completed = 1
    """, (session['user_id'], start_date, end_date))

    completed_prompts = c.fetchall()

    conn.close()

    # Combine journal entries and completed prompts into a dictionary for rendering
    response_data = {}

    for date, entry in journal_entries:
        response_data[date] = {
            'journal_entry': entry,
            'completed_tasks': []
        }

    for date, prompt_number, response in completed_prompts:
        if date in response_data:
            response_data[date]['completed_tasks'].append((prompt_number, response))
        else:
            response_data[date] = {
                'journal_entry': None,
                'completed_tasks': [(prompt_number, response)]
            }

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