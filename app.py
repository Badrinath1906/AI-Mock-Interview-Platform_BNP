import os
import re
import google.generativeai as genai
from dotenv import load_dotenv
from flask import Flask, render_template, request, send_file, redirect
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import mysql.connector

# Load .env file
load_dotenv()

# Configure Gemini API
genai.configure(
    api_key=os.getenv("GEMINI_API_KEY")
)

# Gemini Model
model = genai.GenerativeModel("gemini-2.5-flash")

# Flask App
app = Flask(__name__)

# MySQL Connection
conn = mysql.connector.connect(
    host=os.getenv("MYSQLHOST"),
    user=os.getenv("MYSQLUSER"),
    password=os.getenv("MYSQLPASSWORD"),
    database=os.getenv("MYSQLDATABASE"),
    port=int(os.getenv("MYSQLPORT"))
)

cursor = conn.cursor()

questions = []
answers = []
current_index = 0
current_user = ""
current_user_id = 0

current_company = ""
current_role = ""


# Home Page
@app.route('/')
def home():
    return redirect('/login')

#Start Interviww Page
@app.route('/start-interview')
def start_interview():
    return render_template('index.html')

# Interview Page
@app.route('/interview', methods=['POST'])
def interview():

    # Get form data
    company = request.form['company']
    role = request.form['role']
    global current_company
    global current_role

    current_company = company
    current_role = role

    # Gemini Prompt
    prompt = f"""
Generate 10 interview questions for a {role} role at {company}.

Requirements:
- Suitable for freshers
- Intermediate difficulty
- Mix technical and HR questions
- One line per question
- Number the questions from 1 to 10
- Only return questions
"""

    # Generate Questions
    response = model.generate_content(prompt)

    # Convert Questions to List
    question_list = [
        q.strip()
        for q in response.text.split("\n")
        if q.strip()
    ]
    global questions, current_index
    global answers
    answers = []

    questions = question_list
    current_index = 0

    # First Question
    current_question = question_list[0]

    # Empty Sample Answer
    sample_answer = ""

    return render_template(
        'interview.html',
        role=role,
        company=company,
        question=current_question,
        sample_answer=sample_answer
    )

@app.route('/next_question', methods=['POST'])
def next_question():

    global current_index
    global questions
    global answers

    action = request.form['action']

    answer = request.form.get('answer', '')

    role = request.form['role']
    company = request.form['company']

    # SHOW SAMPLE ANSWER
    if action == "sample":

        sample_prompt = f"""
Question:
{questions[current_index]}

Give the answer in this format:

Point 1:
...

Point 2:
...

Point 3:
...

Point 4:
...

Rules:
- No markdown
- Easy English
- Maximum 5 points
"""

        response = model.generate_content(sample_prompt)

        return render_template(
            'interview.html',
            role=role,
            company=company,
            question=questions[current_index],
            sample_answer=response.text
        )

    # SAVE
    if action == "save":
        answers.append(answer)

    # SKIP
    elif action == "skip":
        answers.append("Skipped")

    current_index += 1

    # Interview Finished
    if current_index >= len(questions):

        skipped = answers.count("Skipped")
        answered = len(answers) - skipped

        return render_template(
            'result.html',
            total=len(questions),
            answered=answered,
            skipped=skipped,
            questions=questions,
            answers=answers
       )

    next_q = questions[current_index]

    return render_template(
        'interview.html',
        role=role,
        company=company,
        question=next_q,
        sample_answer=""
    )
@app.route('/evaluate', methods=['POST'])
def evaluate():

    global questions
    global answers
    global current_company
    global current_role
    global current_user_id

    # Check invalid answers
    invalid_answers = 0

    for ans in answers:

        ans = ans.strip().lower()

        if ans == "skipped" or len(ans.split()) < 5:
            invalid_answers += 1

    # If all answers are invalid
    if invalid_answers == len(answers):

        result = """
Technical Knowledge: 0/10

Communication: 0/10

Problem Solving: 0/10

Overall Score: 0/10

Reason:
Most answers were skipped or too short.

Areas for Improvement:
- Answer questions properly.
- Give detailed explanations.
"""

        overall_score = "0/10"

        cursor.execute(
            """
            INSERT INTO interviews
            ( user_id, company, role, score, evaluation)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                current_user_id,
                current_company,
                current_role,
                overall_score,
                result
            )
        )

        conn.commit()

        technical = 0
        communication = 0
        problem_solving = 0
        tech = re.search(r"Technical Knowledge:\s*(\d+(\.\d+)?)/10", result)
        comm = re.search(r"Communication:\s*(\d+(\.\d+)?)/10", result)
        prob = re.search(r"Problem Solving:\s*(\d+(\.\d+)?)/10", result)

        technical = float(tech.group(1)) if tech else 0
        communication = float(comm.group(1)) if comm else 0
        problem_solving = float(prob.group(1)) if prob else 0

        return render_template(
        'evaluation.html',
        evaluation=result,
        score=overall_score,
        technical=technical,
        communication=communication,
        problem_solving=problem_solving
)
    attempted_answers = len(answers) - invalid_answers 
 
    # Gemini Evaluation Prompt
    evaluation_prompt = f"""
Evaluate this mock interview.

Important Rules:
- Treat "Skipped" as unanswered.
- Do not award marks for skipped answers.
- Answers with fewer than 5 words should receive very low marks.
- If most answers are invalid, overall score should be below 3/10.

Total Questions: {len(answers)}
Valid Answers: {attempted_answers}
Invalid Answers: {invalid_answers}

Questions:
{questions}

Answers:
{answers}

Return in exactly this format:

Technical Knowledge: X/10
Communication: X/10
Problem Solving: X/10
Overall Score: X/10

Strengths:
- Point 1
- Point 2

Areas for Improvement:
- Point 1
- Point 2
"""

    try:

        response = model.generate_content(
            evaluation_prompt
        )

        result = response.text

        overall_score = "N/A"

        match = re.search(
            r"Overall Score:\s*(\d+(\.\d+)?/10)",
            result
        )

        if match:
            overall_score = match.group(1)

    except Exception:

        result = """
Technical Knowledge: 8/10

Communication: 7/10

Problem Solving: 8/10

Overall Score: 8/10

Strengths:
- Good fundamentals
- Clear communication

Areas for Improvement:
- Add more examples
- Improve confidence
"""

        overall_score = "8/10"

    # Save to MySQL
    cursor.execute(
        """
        INSERT INTO interviews
        (user_id, company, role, score, evaluation)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            current_user_id,
            current_company,
            current_role,
            overall_score,
            result
        )
    )

    conn.commit()

    tech = re.search(r"Technical Knowledge:\s*(\d+(\.\d+)?)/10", result)
    comm = re.search(r"Communication:\s*(\d+(\.\d+)?)/10", result)
    prob = re.search(r"Problem Solving:\s*(\d+(\.\d+)?)/10", result)

    technical = float(tech.group(1)) if tech else 0
    communication = float(comm.group(1)) if comm else 0
    problem_solving = float(prob.group(1)) if prob else 0

    return render_template(
    "evaluation.html",
    evaluation=result,
    score=overall_score,
    technical=technical,
    communication=communication,
    problem_solving=problem_solving
)
@app.route('/download_pdf')
def download_pdf():

    pdf = SimpleDocTemplate("Interview_Report.pdf")

    styles = getSampleStyleSheet()

    content = []

    content.append(
        Paragraph("AI Mock Interview Report", styles['Title'])
    )

    content.append(Spacer(1, 20))

    for i in range(len(questions)):

        content.append(
            Paragraph(
                f"<b>Question {i+1}:</b> {questions[i]}",
                styles['Normal']
            )
        )

        content.append(
            Paragraph(
                f"<b>Answer:</b> {answers[i]}",
                styles['Normal']
            )
        )

        content.append(Spacer(1, 10))

    pdf.build(content)

    return send_file(
      "Interview_Report.pdf",
      as_attachment=True
)
@app.route('/history')
def history():

    cursor.execute(
    """
    SELECT *
    FROM interviews
    WHERE user_id=%s
    ORDER BY id DESC
    """,
    (current_user_id,)
)

    interviews = cursor.fetchall()

    return render_template(
        'history.html',
        interviews=interviews
    )


@app.route('/dashboard')
def dashboard():

    global current_user
    global current_user_id

    # Protect Dashboard
    if current_user == "":
        return redirect('/login')

    # Total Interviews (User Wise)
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM interviews
        WHERE user_id=%s
        """,
        (current_user_id,)
    )

    total = cursor.fetchone()[0]

    # Highest Score (User Wise)
    cursor.execute(
        """
        SELECT MAX(
        CAST(REPLACE(score,'/10','') AS DECIMAL(4,2))
        )
        FROM interviews
        WHERE user_id=%s
        """,
        (current_user_id,)
    )

    highest = cursor.fetchone()[0]

    if highest is None:
        highest = 0

    # Success Rate
    success_rate = round(
        (highest / 10) * 100
    ) if highest else 0

    # Average Score (User Wise)
    cursor.execute(
        """
        SELECT AVG(
        CAST(REPLACE(score,'/10','') AS DECIMAL(4,2))
        )
        FROM interviews
        WHERE user_id=%s
        """,
        (current_user_id,)
    )

    average = cursor.fetchone()[0]

    if average:
        average = round(average, 2)
    else:
        average = 0

    # Recent Interviews (User Wise)
    cursor.execute(
        """
        SELECT *
        FROM interviews
        WHERE user_id=%s
        ORDER BY id DESC
        LIMIT 5
        """,
        (current_user_id,)
    )

    recent = cursor.fetchall()

    return render_template(
        'dashboard.html',
        total=total,
        highest=highest,
        success=success_rate,
        average=average,
        recent=recent,
        username=current_user
    )

@app.route('/register')
def register():
    return render_template('register.html')

@app.route('/register_user', methods=['POST'])
def register_user():

    name = request.form['name']
    email = request.form['email']
    password = request.form['password']

    cursor.execute(
        """
        INSERT INTO users
        (name,email,password)
        VALUES (%s,%s,%s)
        """,
        (name,email,password)
    )

    conn.commit()

    return redirect('/login')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/login_user', methods=['POST'])
def login_user():

    email = request.form['email']
    password = request.form['password']

    cursor.execute(
        """
        SELECT * FROM users
        WHERE email=%s
        AND password=%s
        """,
        (email, password)
    )

    user = cursor.fetchone()

    if user:

        global current_user
        global current_user_id

        current_user_id = user[0]
        current_user = user[1]

        return redirect('/dashboard')

    return "Invalid Email or Password"

#Logout
@app.route('/logout')
def logout():

    global current_user
    current_user = ""

    return redirect('/login')

@app.route('/forgot_password')
def forgot_password():
    return render_template('forgot_password.html')

@app.route('/reset_password', methods=['POST'])
def reset_password():

    email = request.form['email']
    new_password = request.form['new_password']
    confirm_password = request.form['confirm_password']

    # Password Match Check
    if new_password != confirm_password:
        return "❌ Passwords do not match"

    # Check Email Exists
    cursor.execute(
        """
        SELECT * FROM users
        WHERE email=%s
        """,
        (email,)
    )

    user = cursor.fetchone()

    if user is None:
        return "❌ Email not found"

    # Update Password
    cursor.execute(
        """
        UPDATE users
        SET password=%s
        WHERE email=%s
        """,
        (new_password, email)
    )

    conn.commit()

    return redirect('/login')

# Run App
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
