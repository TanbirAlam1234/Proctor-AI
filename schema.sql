-- ProctorAI database schema (SQLite)

DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS exams;
DROP TABLE IF EXISTS results;
DROP TABLE IF EXISTS violation_logs;
DROP TABLE IF EXISTS exam_sessions;
DROP TABLE IF EXISTS questions;
DROP TABLE IF EXISTS student_answers;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    roll_no TEXT UNIQUE,              -- used for students; NULL for admins
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','student')),
    batch TEXT,                       -- e.g. CSE-3B (students only)
    face_registered INTEGER DEFAULT 0,
    photo_data TEXT,                  -- registered ID photo (base64 JPEG), uploaded by the admin
    face_descriptor TEXT,             -- 128-number face fingerprint of that photo (JSON), used for matching
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    subject TEXT,
    batch TEXT NOT NULL,              -- which batch this exam is assigned to
    duration_minutes INTEGER NOT NULL,
    total_marks INTEGER DEFAULT 100,
    scheduled_at TEXT NOT NULL,       -- ISO datetime string
    proctoring_level TEXT DEFAULT 'Full',
    exam_password TEXT NOT NULL DEFAULT 'EXAM123',   -- students must enter this to join
    created_by INTEGER,
    FOREIGN KEY(created_by) REFERENCES users(id)
);

CREATE TABLE results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    exam_id INTEGER NOT NULL,
    score INTEGER,
    total INTEGER,
    risk_score INTEGER DEFAULT 0,
    violations_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'submitted',  -- submitted, published
    submitted_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(student_id) REFERENCES users(id),
    FOREIGN KEY(exam_id) REFERENCES exams(id)
);

CREATE TABLE violation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    exam_id INTEGER NOT NULL,
    module TEXT NOT NULL,             -- Face Detection, Eye Tracking, Head Pose, Object Detection, Audio
    event TEXT NOT NULL,
    severity TEXT NOT NULL,           -- Low, Medium, High
    snapshot_data TEXT,               -- base64 JPEG captured from the webcam at the moment of the violation
    timestamp TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(student_id) REFERENCES users(id),
    FOREIGN KEY(exam_id) REFERENCES exams(id)
);

-- Tracks who is CURRENTLY sitting an exam right now, for the admin Live Monitor.
CREATE TABLE exam_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    exam_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'in_progress',   -- in_progress, submitted
    started_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(student_id, exam_id),
    FOREIGN KEY(student_id) REFERENCES users(id),
    FOREIGN KEY(exam_id) REFERENCES exams(id)
);

-- Questions the admin adds for a specific exam (MCQ only, for now).
CREATE TABLE questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    option_a TEXT NOT NULL,
    option_b TEXT NOT NULL,
    option_c TEXT NOT NULL,
    option_d TEXT NOT NULL,
    correct_option TEXT NOT NULL CHECK(correct_option IN ('a','b','c','d')),
    marks INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(exam_id) REFERENCES exams(id)
);

-- Each answer a student actually submitted, per question, for grading + review.
CREATE TABLE student_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    exam_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    selected_option TEXT,             -- a, b, c, d, or NULL if left blank
    is_correct INTEGER NOT NULL DEFAULT 0,
    UNIQUE(student_id, question_id),
    FOREIGN KEY(student_id) REFERENCES users(id),
    FOREIGN KEY(exam_id) REFERENCES exams(id),
    FOREIGN KEY(question_id) REFERENCES questions(id)
);
