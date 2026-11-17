"""
ProctorAI — Flask backend
Run:
    pip install flask
    python seed.py       (creates + fills the database, run once)
    python app.py         (starts the server)
Then open http://127.0.0.1:5000
"""
import json
import math
import sqlite3
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-this-before-real-deployment"
DB_PATH = "instance/proctorai.db"

# --- Identity (face-match) settings ---------------------------------------
# Max allowed distance between the live face and the registered ID photo.
# With face-api.js descriptors the same person is usually < 0.45 and different
# people usually > 0.6, so 0.5 is a sensible middle.
FACE_MATCH_THRESHOLD = 0.5
MAX_ID_FAILURES = 5          # failed matches allowed per exam in any 15-minute window
# DEV ONLY: if True, a student with NO registered photo gets their first live
# capture saved as their reference. Keep False for real exams - the reference
# must come from the admin-registered ID photo.
ALLOW_FIRST_USE_ENROLLMENT = False


def _valid_descriptor(d):
    return (isinstance(d, list) and len(d) == 128
            and all(isinstance(x, (int, float)) and math.isfinite(x) for x in d)
            and any(abs(x) > 1e-6 for x in d))


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------------------------------------------------------------------------
# Auth helpers / decorators
# ---------------------------------------------------------------------------
def login_required(role=None):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                return redirect(url_for("login"))
            return view_func(*args, **kwargs)
        return wrapped
    return decorator


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role")
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "").strip()

        db = get_db()
        if role == "admin":
            user = db.execute(
                "SELECT * FROM users WHERE role='admin' AND (email=? OR name=?)",
                (identifier, identifier),
            ).fetchone()
        else:
            user = db.execute(
                "SELECT * FROM users WHERE role='student' AND (roll_no=? OR email=?)",
                (identifier, identifier),
            ).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Incorrect name/ID or password. Please try again.")
            return render_template("login.html", role=role, identifier=identifier)

        session["user_id"] = user["id"]
        session["role"] = user["role"]
        session["name"] = user["name"]

        if user["role"] == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("student_dashboard"))

    return render_template("login.html", role="admin", identifier="")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------
@app.route("/admin/dashboard")
@login_required(role="admin")
def admin_dashboard():
    db = get_db()
    students = db.execute("SELECT * FROM users WHERE role='student' ORDER BY name").fetchall()
    exams = db.execute("SELECT * FROM exams ORDER BY scheduled_at DESC").fetchall()
    logs = db.execute("""
        SELECT violation_logs.*, users.name AS student_name
        FROM violation_logs JOIN users ON violation_logs.student_id = users.id
        ORDER BY violation_logs.timestamp DESC LIMIT 20
    """).fetchall()
    results = db.execute("""
        SELECT results.*, users.name AS student_name, exams.title AS exam_title
        FROM results
        JOIN users ON results.student_id = users.id
        JOIN exams ON results.exam_id = exams.id
        ORDER BY results.submitted_at DESC
    """).fetchall()

    total_students = len(students)
    flagged_count = sum(1 for r in results if r["risk_score"] >= 50)

    live_sessions = db.execute("""
        SELECT exam_sessions.*, users.name AS student_name, users.roll_no,
               exams.title AS exam_title, exams.duration_minutes
        FROM exam_sessions
        JOIN users ON exam_sessions.student_id = users.id
        JOIN exams ON exam_sessions.exam_id = exams.id
        WHERE exam_sessions.status = 'in_progress'
        ORDER BY exam_sessions.started_at DESC
    """).fetchall()

    branches = [r["batch"] for r in db.execute(
        "SELECT DISTINCT batch FROM users WHERE role='student' ORDER BY batch"
    ).fetchall()]

    exam_log_summary = db.execute("""
        SELECT exams.id, exams.title, exams.subject, exams.batch, exams.scheduled_at,
               COUNT(violation_logs.id) AS violation_count,
               SUM(CASE WHEN violation_logs.severity='High' THEN 1 ELSE 0 END) AS high_count
        FROM exams
        LEFT JOIN violation_logs ON violation_logs.exam_id = exams.id
        GROUP BY exams.id
        ORDER BY violation_count DESC, exams.scheduled_at DESC
    """).fetchall()

    return render_template(
        "admin_dashboard.html",
        students=students, exams=exams, logs=logs, results=results,
        total_students=total_students, flagged_count=flagged_count,
        live_sessions=live_sessions,
        branches=branches,
        exam_log_summary=exam_log_summary,
        name=session.get("name"),
    )


@app.route("/admin/api/live-sessions")
@login_required(role="admin")
def admin_live_sessions_api():
    db = get_db()
    rows = db.execute("""
        SELECT exam_sessions.id, users.name AS student_name, users.roll_no,
               exams.title AS exam_title, exam_sessions.started_at
        FROM exam_sessions
        JOIN users ON exam_sessions.student_id = users.id
        JOIN exams ON exam_sessions.exam_id = exams.id
        WHERE exam_sessions.status = 'in_progress'
        ORDER BY exam_sessions.started_at DESC
    """).fetchall()
    return {"count": len(rows), "sessions": [dict(r) for r in rows]}


@app.route("/admin/exams/create", methods=["POST"])
@login_required(role="admin")
def admin_create_exam():
    title = request.form.get("title", "").strip()
    subject = request.form.get("subject", "").strip()
    batch = request.form.get("batch", "").strip()
    duration_minutes = request.form.get("duration_minutes", "").strip()
    total_marks = request.form.get("total_marks", "").strip()
    scheduled_at = request.form.get("scheduled_at", "").strip()
    proctoring_level = request.form.get("proctoring_level", "Full").strip()
    exam_password = request.form.get("exam_password", "").strip()

    errors = []
    if not title: errors.append("Exam title is required.")
    if not batch: errors.append("Batch is required.")
    if not scheduled_at: errors.append("Scheduled date & time is required.")
    if not exam_password: errors.append("Exam password is required.")
    if not duration_minutes.isdigit() or int(duration_minutes) <= 0:
        errors.append("Duration must be a positive number of minutes.")
    if total_marks and not total_marks.isdigit():
        errors.append("Total marks must be a number.")

    if errors:
        for e in errors:
            flash(e)
        return redirect(url_for("admin_dashboard", _anchor="exams"))

    db = get_db()
    db.execute("""
        INSERT INTO exams (title, subject, batch, duration_minutes, total_marks, scheduled_at, proctoring_level, exam_password, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, subject, batch, int(duration_minutes), int(total_marks or 100), scheduled_at, proctoring_level, exam_password, session["user_id"]))
    db.commit()

    flash(f'Exam "{title}" created successfully.')
    return redirect(url_for("admin_dashboard", _anchor="exams"))


@app.route("/admin/students/<int:student_id>/photo", methods=["POST"])
@login_required(role="admin")
def admin_register_photo(student_id):
    """Admin registers (or replaces) a student's ID photo + its face fingerprint.
    The fingerprint is computed in the admin's browser; it is never sent to students."""
    data = request.get_json(silent=True) or {}
    photo = data.get("photo")
    descriptor = data.get("descriptor")

    if (not isinstance(photo, str) or len(photo) > 400_000
            or not photo.startswith(("data:image/jpeg;base64,", "data:image/png;base64,"))):
        return {"ok": False, "error": "invalid_photo"}, 400
    if not _valid_descriptor(descriptor):
        return {"ok": False, "error": "invalid_descriptor"}, 400

    db = get_db()
    student = db.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
    if student is None:
        return {"ok": False, "error": "not_found"}, 404

    db.execute(
        "UPDATE users SET photo_data=?, face_descriptor=?, face_registered=1 WHERE id=?",
        (photo, json.dumps(descriptor), student_id),
    )
    db.commit()
    flash(f'ID photo registered for {student["name"]}.')
    return {"ok": True}


@app.route("/admin/students/create", methods=["POST"])
@login_required(role="admin")
def admin_create_student():
    name = request.form.get("name", "").strip()
    roll_no = request.form.get("roll_no", "").strip()
    email = request.form.get("email", "").strip()
    batch = request.form.get("batch", "").strip()
    password = request.form.get("password", "").strip()

    errors = []
    if not name: errors.append("Student name is required.")
    if not roll_no: errors.append("Roll number is required.")
    if not batch: errors.append("Batch is required.")
    if len(password) < 6: errors.append("Password must be at least 6 characters.")

    if errors:
        for e in errors:
            flash(e)
        return redirect(url_for("admin_dashboard", _anchor="students"))

    db = get_db()
    try:
        db.execute("""
            INSERT INTO users (name, roll_no, email, password_hash, role, batch, face_registered)
            VALUES (?, ?, ?, ?, 'student', ?, 0)
        """, (name, roll_no, email or None, generate_password_hash(password), batch))
        db.commit()
    except sqlite3.IntegrityError:
        flash(f'A student with roll number "{roll_no}" or that email already exists.')
        return redirect(url_for("admin_dashboard", _anchor="students"))

    flash(f'Student "{name}" added successfully.')
    return redirect(url_for("admin_dashboard", _anchor="students"))


@app.route("/admin/exams/<int:exam_id>/logs")
@login_required(role="admin")
def admin_exam_logs(exam_id):
    db = get_db()
    exam = db.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
    if exam is None:
        flash("That exam could not be found.")
        return redirect(url_for("admin_dashboard", _anchor="logs"))

    logs = db.execute("""
        SELECT violation_logs.*, users.name AS student_name, users.roll_no
        FROM violation_logs JOIN users ON violation_logs.student_id = users.id
        WHERE violation_logs.exam_id = ?
        ORDER BY violation_logs.timestamp DESC
    """, (exam_id,)).fetchall()

    return render_template("admin_exam_logs.html", exam=exam, logs=logs, name=session.get("name"))


@app.route("/admin/exams/<int:exam_id>/roster")
@login_required(role="admin")
def admin_exam_roster(exam_id):
    db = get_db()
    exam = db.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
    if exam is None:
        flash("That exam could not be found.")
        return redirect(url_for("admin_dashboard", _anchor="exams"))

    students = db.execute(
        "SELECT * FROM users WHERE role='student' AND batch=? ORDER BY name", (exam["batch"],)
    ).fetchall()

    sessions = {s["student_id"]: s for s in db.execute(
        "SELECT * FROM exam_sessions WHERE exam_id=?", (exam_id,)
    ).fetchall()}
    results = {r["student_id"]: r for r in db.execute(
        "SELECT * FROM results WHERE exam_id=?", (exam_id,)
    ).fetchall()}

    roster = []
    for s in students:
        result = results.get(s["id"])
        sess = sessions.get(s["id"])
        if result:
            status = "submitted"
        elif sess and sess["status"] == "in_progress":
            status = "in_progress"
        else:
            status = "not_started"
        roster.append({"student": s, "status": status, "result": result, "session": sess})

    return render_template(
        "admin_exam_roster.html", exam=exam, roster=roster, name=session.get("name"),
    )


@app.route("/admin/exams/<int:exam_id>/questions")
@login_required(role="admin")
def admin_exam_questions(exam_id):
    db = get_db()
    exam = db.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
    if exam is None:
        flash("That exam could not be found.")
        return redirect(url_for("admin_dashboard", _anchor="exams"))

    questions = db.execute(
        "SELECT * FROM questions WHERE exam_id=? ORDER BY id", (exam_id,)
    ).fetchall()

    return render_template(
        "admin_exam_questions.html", exam=exam, questions=questions, name=session.get("name"),
    )


@app.route("/admin/exams/<int:exam_id>/questions/add", methods=["POST"])
@login_required(role="admin")
def admin_add_question(exam_id):
    db = get_db()
    exam = db.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
    if exam is None:
        flash("That exam could not be found.")
        return redirect(url_for("admin_dashboard", _anchor="exams"))

    question_text = request.form.get("question_text", "").strip()
    option_a = request.form.get("option_a", "").strip()
    option_b = request.form.get("option_b", "").strip()
    option_c = request.form.get("option_c", "").strip()
    option_d = request.form.get("option_d", "").strip()
    correct_option = request.form.get("correct_option", "").strip()
    marks = request.form.get("marks", "1").strip()

    errors = []
    if not question_text: errors.append("Question text is required.")
    if not all([option_a, option_b, option_c, option_d]): errors.append("All 4 options are required.")
    if correct_option not in ("a", "b", "c", "d"): errors.append("You must select which option is correct.")
    if not marks.isdigit() or int(marks) <= 0: errors.append("Marks must be a positive number.")

    if errors:
        for e in errors:
            flash(e)
        return redirect(url_for("admin_exam_questions", exam_id=exam_id))

    db.execute("""
        INSERT INTO questions (exam_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (exam_id, question_text, option_a, option_b, option_c, option_d, correct_option, int(marks)))
    db.commit()

    flash("Question added successfully.")
    return redirect(url_for("admin_exam_questions", exam_id=exam_id))


@app.route("/admin/exams/<int:exam_id>/questions/<int:question_id>/delete", methods=["POST"])
@login_required(role="admin")
def admin_delete_question(exam_id, question_id):
    db = get_db()
    db.execute("DELETE FROM questions WHERE id=? AND exam_id=?", (question_id, exam_id))
    db.commit()
    flash("Question removed.")
    return redirect(url_for("admin_exam_questions", exam_id=exam_id))


# ---------------------------------------------------------------------------
# Student routes
# ---------------------------------------------------------------------------
@app.route("/student/dashboard")
@login_required(role="student")
def student_dashboard():
    db = get_db()
    student_id = session["user_id"]
    student = db.execute("SELECT * FROM users WHERE id=?", (student_id,)).fetchone()

    # All exams assigned to this student's batch
    all_exams = db.execute(
        "SELECT * FROM exams WHERE batch=? ORDER BY scheduled_at", (student["batch"],)
    ).fetchall()

    # Results already submitted by this student
    results = db.execute("""
        SELECT results.*, exams.title, exams.subject, exams.scheduled_at, exams.total_marks
        FROM results JOIN exams ON results.exam_id = exams.id
        WHERE results.student_id=?
        ORDER BY exams.scheduled_at DESC
    """, (student_id,)).fetchall()
    attempted_exam_ids = {r["exam_id"] for r in results}

    now_iso = datetime.now().isoformat(timespec="minutes")
    today_date = datetime.now().isoformat()[:10]

    not_attempted = [e for e in all_exams if e["id"] not in attempted_exam_ids]
    today_exam = next((e for e in not_attempted if e["scheduled_at"][:10] == today_date), None)
    upcoming = [e for e in not_attempted if e["scheduled_at"][:10] != today_date and e["scheduled_at"] >= now_iso]
    upcoming.sort(key=lambda e: e["scheduled_at"])

    total_assigned = len(all_exams)
    attended_count = len(results)
    attendance_pct = round((attended_count / total_assigned) * 100) if total_assigned else 0
    avg_score_pct = 0
    if results:
        pct_list = [ (r["score"] / r["total"]) * 100 for r in results if r["total"] ]
        avg_score_pct = round(sum(pct_list) / len(pct_list)) if pct_list else 0

    return render_template(
        "student_dashboard.html",
        student=student,
        today_exam=today_exam,
        upcoming=upcoming,
        results=results,
        total_assigned=total_assigned,
        attended_count=attended_count,
        attendance_pct=attendance_pct,
        avg_score_pct=avg_score_pct,
        name=session.get("name"),
    )


def _get_student_exam_or_404(exam_id):
    """Fetch an exam and make sure it belongs to the logged-in student's batch."""
    db = get_db()
    student = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    exam = db.execute("SELECT * FROM exams WHERE id=? AND batch=?", (exam_id, student["batch"])).fetchone()
    return student, exam


@app.route("/student/exam/<int:exam_id>/details")
@login_required(role="student")
def exam_details(exam_id):
    student, exam = _get_student_exam_or_404(exam_id)
    if exam is None:
        flash("That exam could not be found.")
        return redirect(url_for("student_dashboard"))

    db = get_db()
    already = db.execute(
        "SELECT * FROM results WHERE student_id=? AND exam_id=?", (session["user_id"], exam_id)
    ).fetchone()

    exam_date = exam["scheduled_at"][:10]
    today_date = datetime.now().isoformat()[:10]
    is_today = exam_date == today_date

    return render_template(
        "exam_details.html",
        exam=exam, already=already, is_today=is_today, name=session.get("name"),
    )


@app.route("/student/exam/<int:exam_id>/join", methods=["POST"])
@login_required(role="student")
def exam_join(exam_id):
    student, exam = _get_student_exam_or_404(exam_id)
    if exam is None:
        flash("That exam could not be found.")
        return redirect(url_for("student_dashboard"))

    exam_date = exam["scheduled_at"][:10]
    today_date = datetime.now().isoformat()[:10]
    if exam_date != today_date:
        flash("This exam is not available to join yet. Come back on the scheduled date.")
        return redirect(url_for("exam_details", exam_id=exam_id))

    entered_password = request.form.get("exam_password", "").strip()
    if entered_password != exam["exam_password"]:
        flash("Incorrect exam password. Check with your instructor and try again.")
        return redirect(url_for("exam_details", exam_id=exam_id))

    # Password correct -> grant access to the verification (system check) step only.
    # NOTE: this does NOT yet grant access to the exam itself.
    session[f"exam_access_{exam_id}"] = True
    session.pop(f"exam_verified_{exam_id}", None)  # must re-verify each time they join
    session.pop(f"exam_identity_ok_{exam_id}", None)
    return redirect(url_for("exam_check", exam_id=exam_id))


@app.route("/student/exam/<int:exam_id>/check")
@login_required(role="student")
def exam_check(exam_id):
    student, exam = _get_student_exam_or_404(exam_id)
    if exam is None:
        flash("That exam could not be found.")
        return redirect(url_for("student_dashboard"))

    # Gate: must have entered the correct exam password first.
    if not session.get(f"exam_access_{exam_id}"):
        flash("Please enter the exam password first.")
        return redirect(url_for("exam_details", exam_id=exam_id))

    return render_template(
        "exam_check.html", exam=exam, name=session.get("name"),
        has_reference=bool(student["face_descriptor"]),
        allow_first_use=ALLOW_FIRST_USE_ENROLLMENT,
    )


@app.route("/student/exam/<int:exam_id>/verify-id", methods=["POST"])
@login_required(role="student")
def exam_verify_id(exam_id):
    """Server-side face match: live face fingerprint (from the student's browser)
    vs the fingerprint of the ID photo the admin registered."""
    student, exam = _get_student_exam_or_404(exam_id)
    if exam is None or not session.get(f"exam_access_{exam_id}"):
        return {"ok": False, "error": "not_authorized"}, 403

    db = get_db()
    recent_failures = db.execute("""
        SELECT COUNT(*) FROM violation_logs
        WHERE student_id=? AND exam_id=? AND module='Identity Verification'
          AND timestamp > datetime('now', '-15 minutes')
    """, (student["id"], exam_id)).fetchone()[0]
    if recent_failures >= MAX_ID_FAILURES:
        return {"ok": False, "error": "too_many_attempts"}, 429

    data = request.get_json(silent=True) or {}
    live = data.get("descriptor")
    snapshot = data.get("snapshot")
    if not _valid_descriptor(live):
        return {"ok": False, "error": "invalid_descriptor"}, 400

    if not student["face_descriptor"]:
        if ALLOW_FIRST_USE_ENROLLMENT:
            db.execute("UPDATE users SET face_descriptor=?, face_registered=1 WHERE id=?",
                       (json.dumps(live), student["id"]))
            db.commit()
            session[f"exam_identity_ok_{exam_id}"] = True
            return {"ok": True, "enrolled": True}
        return {"ok": False, "error": "no_reference"}, 409

    distance = math.dist(json.loads(student["face_descriptor"]), live)
    if distance <= FACE_MATCH_THRESHOLD:
        session[f"exam_identity_ok_{exam_id}"] = True
        return {"ok": True, "distance": round(distance, 3)}

    snap = snapshot if (isinstance(snapshot, str) and len(snapshot) < 200_000
                        and snapshot.startswith("data:image/jpeg;base64,")) else None
    db.execute("""
        INSERT INTO violation_logs (student_id, exam_id, module, event, severity, snapshot_data)
        VALUES (?, ?, 'Identity Verification', ?, 'High', ?)
    """, (student["id"], exam_id,
          f"Face did not match registered ID photo (distance {distance:.2f})", snap))
    db.commit()
    left = MAX_ID_FAILURES - (recent_failures + 1)
    return {"ok": False, "error": "mismatch", "distance": round(distance, 3), "attempts_left": left}


@app.route("/student/exam/<int:exam_id>/verify", methods=["POST"])
@login_required(role="student")
def exam_verify(exam_id):
    """Called by JS only after Face check + Fullscreen + ID confirmation all pass."""
    student, exam = _get_student_exam_or_404(exam_id)
    if exam is None or not session.get(f"exam_access_{exam_id}"):
        return {"ok": False, "error": "not_authorized"}, 403

    # The identity match is decided by the SERVER (see exam_verify_id) - the browser cannot claim it.
    if not session.get(f"exam_identity_ok_{exam_id}"):
        return {"ok": False, "error": "identity_not_verified"}, 403

    face_ok = request.form.get("face_ok") == "1"
    fullscreen_ok = request.form.get("fullscreen_ok") == "1"
    id_ok = request.form.get("id_ok") == "1"

    if not (face_ok and fullscreen_ok and id_ok):
        return {"ok": False, "error": "incomplete_verification"}, 400

    # All 3 checks passed -> NOW grant access to the actual exam.
    session[f"exam_verified_{exam_id}"] = True
    return {"ok": True, "redirect": url_for("exam_take", exam_id=exam_id)}


@app.route("/student/exam/<int:exam_id>/take")
@login_required(role="student")
def exam_take(exam_id):
    student, exam = _get_student_exam_or_404(exam_id)
    if exam is None:
        flash("That exam could not be found.")
        return redirect(url_for("student_dashboard"))

    # Hard gate: cannot reach the exam without password AND full verification.
    if not session.get(f"exam_access_{exam_id}"):
        flash("Please enter the exam password first.")
        return redirect(url_for("exam_details", exam_id=exam_id))
    if not session.get(f"exam_verified_{exam_id}"):
        flash("Please complete face, fullscreen, and ID verification first.")
        return redirect(url_for("exam_check", exam_id=exam_id))

    # Mark this student as LIVE / in-progress so the admin's Live Monitor can see it.
    db = get_db()
    db.execute("""
        INSERT INTO exam_sessions (student_id, exam_id, status, started_at, updated_at)
        VALUES (?, ?, 'in_progress', datetime('now'), datetime('now'))
        ON CONFLICT(student_id, exam_id)
        DO UPDATE SET status='in_progress', updated_at=datetime('now')
    """, (session["user_id"], exam_id))
    db.commit()

    questions = db.execute(
        "SELECT * FROM questions WHERE exam_id=? ORDER BY id", (exam_id,)
    ).fetchall()

    return render_template("exam_take.html", exam=exam, questions=questions, name=session.get("name"))


@app.route("/student/exam/<int:exam_id>/log-violation", methods=["POST"])
@login_required(role="student")
def exam_log_violation(exam_id):
    student, exam = _get_student_exam_or_404(exam_id)
    if exam is None or not session.get(f"exam_verified_{exam_id}"):
        return {"ok": False, "error": "not_authorized"}, 403

    data = request.get_json(silent=True) or {}
    module = data.get("module", "").strip()
    event = data.get("event", "").strip()
    severity = data.get("severity", "Medium").strip()
    snapshot = data.get("snapshot")   # base64 JPEG data URI, optional

    if not module or not event or severity not in ("Low", "Medium", "High"):
        return {"ok": False, "error": "invalid_payload"}, 400

    db = get_db()
    db.execute("""
        INSERT INTO violation_logs (student_id, exam_id, module, event, severity, snapshot_data)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (session["user_id"], exam_id, module, event, severity, snapshot))
    db.commit()

    return {"ok": True}


@app.route("/student/exam/<int:exam_id>/submit", methods=["POST"])
@login_required(role="student")
def exam_submit(exam_id):
    student, exam = _get_student_exam_or_404(exam_id)
    if exam is None or not session.get(f"exam_verified_{exam_id}"):
        flash("You must complete verification before submitting.")
        return redirect(url_for("student_dashboard"))

    db = get_db()
    questions = db.execute("SELECT * FROM questions WHERE exam_id=?", (exam_id,)).fetchall()

    total_marks = sum(q["marks"] for q in questions) if questions else exam["total_marks"]
    score = 0

    for q in questions:
        selected = request.form.get(f"q_{q['id']}")  # 'a' / 'b' / 'c' / 'd' / None if left blank
        is_correct = 1 if selected == q["correct_option"] else 0
        if is_correct:
            score += q["marks"]

        db.execute("""
            INSERT INTO student_answers (student_id, exam_id, question_id, selected_option, is_correct)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_id, question_id)
            DO UPDATE SET selected_option=excluded.selected_option, is_correct=excluded.is_correct
        """, (session["user_id"], exam_id, q["id"], selected, is_correct))

    db.execute("""
        INSERT INTO results (student_id, exam_id, score, total, risk_score, violations_count, status)
        VALUES (?, ?, ?, ?, ?, ?, 'submitted')
    """, (session["user_id"], exam_id, score, total_marks, 0, 0))
    db.execute("""
        UPDATE exam_sessions SET status='submitted', updated_at=datetime('now')
        WHERE student_id=? AND exam_id=?
    """, (session["user_id"], exam_id))
    db.commit()

    # Clear this exam's access/verification flags so it can't be re-entered.
    session.pop(f"exam_access_{exam_id}", None)
    session.pop(f"exam_verified_{exam_id}", None)

    flash("Exam submitted successfully.")
    return redirect(url_for("student_dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
