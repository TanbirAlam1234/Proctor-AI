"""
Run this once to create the database and fill it with demo data:
    python seed.py
"""
import sqlite3
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta

DB_PATH = "instance/proctorai.db"

conn = sqlite3.connect(DB_PATH)
with open("schema.sql") as f:
    conn.executescript(f.read())

cur = conn.cursor()

# ---- Admin ----
cur.execute("""
    INSERT INTO users (name, email, password_hash, role)
    VALUES (?, ?, ?, 'admin')
""", ("Ariba Kounain", "admin@proctorai.edu", generate_password_hash("admin123")))
admin_id = cur.lastrowid

# ---- Students ----
students = [
    ("S. Sreeharsha", "23C31A05F3", "sreeharsha@cse.edu", "CSE-3B"),
    ("T. Rajesh",      "23C31A05G3", "rajesh.t@cse.edu",   "CSE-3B"),
    ("Tanbir Alam",    "23C31A05G1", "tanbir.a@cse.edu",   "CSE-3B"),
    ("V. Pranisha",    "23C31A05H5", "pranisha.v@cse.edu", "CSE-3B"),
    ("R. Meghana",     "23C31A05K7", "meghana.r@cse.edu",  "CSE-3B"),
    ("K. Devika",      "23C32A04B1", "devika.k@ece.edu",   "ECE-2A"),
    ("N. Bhavesh",     "23C32A04B2", "bhavesh.n@ece.edu",  "ECE-2A"),
    ("A. Kiran",       "23C33A03C1", "kiran.a@mech.edu",   "MECH-1B"),
]
student_ids = {}
for name, roll, email, batch in students:
    cur.execute("""
        INSERT INTO users (name, roll_no, email, password_hash, role, batch, face_registered)
        VALUES (?, ?, ?, ?, 'student', ?, 0)
    """, (name, roll, email, generate_password_hash("student123"), batch))
    student_ids[roll] = cur.lastrowid

demo_student_id = student_ids["23C31A05F3"]  # the one we log in as in the demo

# ---- Exams ----
now = datetime.now()
exams = [
    ("Data Structures — Mid Sem", "Data Structures", "CSE-3B", 60, 100, now - timedelta(days=10), "Full", "DS100"),
    ("Computer Networks — Quiz 2", "Computer Networks", "CSE-3B", 30, 50, now - timedelta(days=5), "Standard", "CN050"),
    ("DBMS — Final Exam", "DBMS", "CSE-3B", 120, 100, now - timedelta(days=2), "Full", "DBM100"),
    ("Operating Systems — Unit Test", "Operating Systems", "CSE-3B", 90, 100, now.replace(hour=15, minute=0), "Full", "OS900"),
    ("Computer Networks — Final", "Computer Networks", "CSE-3B", 120, 100, now + timedelta(days=9), "Full", "CN200"),
]
exam_ids = []
for title, subject, batch, dur, total, sched, level, pw in exams:
    cur.execute("""
        INSERT INTO exams (title, subject, batch, duration_minutes, total_marks, scheduled_at, proctoring_level, exam_password, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, subject, batch, dur, total, sched.isoformat(timespec="minutes"), level, pw, admin_id))
    exam_ids.append(cur.lastrowid)

# ---- Results for the demo student (first 3 exams already happened) ----
demo_results = [
    (exam_ids[0], 92, 100, 4, 0),
    (exam_ids[1], 41, 50, 9, 0),
    (exam_ids[2], 88, 100, 6, 1),
]
for exam_id, score, total, risk, violations in demo_results:
    cur.execute("""
        INSERT INTO results (student_id, exam_id, score, total, risk_score, violations_count, status)
        VALUES (?, ?, ?, ?, ?, ?, 'published')
    """, (demo_student_id, exam_id, score, total, risk, violations))

# ---- A couple of sample violation logs (for admin Activity Logs page) ----
cur.execute("""INSERT INTO violation_logs (student_id, exam_id, module, event, severity)
               VALUES (?, ?, 'Object Detection', 'Mobile phone detected in frame', 'High')""",
            (student_ids["23C31A05G3"], exam_ids[2]))
cur.execute("""INSERT INTO violation_logs (student_id, exam_id, module, event, severity)
               VALUES (?, ?, 'Face Detection', 'Second face detected', 'High')""",
            (student_ids["23C31A05K7"], exam_ids[2]))

# ---- Sample questions for today's exam (Operating Systems) ----
os_exam_id = exam_ids[3]  # "Operating Systems — Unit Test"
questions = [
    ("Which scheduling algorithm can cause starvation?", "Round Robin", "Priority Scheduling", "FCFS", "SJF", "b", 1),
    ("What is a deadlock?", "A process running forever", "Two or more processes waiting on each other forever", "A CPU overheating", "A memory leak", "b", 1),
    ("Which of these is NOT a page replacement algorithm?", "LRU", "FIFO", "Optimal", "Round Robin", "d", 1),
    ("A thread shares which of the following with other threads in the same process?", "Stack", "Register set", "Address space", "Program counter", "c", 1),
]
for q_text, a, b, c, d, correct, marks in questions:
    cur.execute("""
        INSERT INTO questions (exam_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (os_exam_id, q_text, a, b, c, d, correct, marks))

conn.commit()
conn.close()

print("Database created at", DB_PATH)
print("\nDemo login credentials:")
print("  Admin   -> name: admin@proctorai.edu   password: admin123")
print("  Student -> name: 23C31A05F3            password: student123")
print("\nToday's exam password (Operating Systems — Unit Test): OS900")
print("NOTE: students need a registered ID photo before they can verify.")
print("      Admin -> Students -> 'Register photo' (one per student).")
