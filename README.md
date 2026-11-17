<<<<<<< HEAD
# ProctorAI — Flask Backend (Starter)

A working Flask + SQLite backend for your AI Exam Proctoring project, with real
login (hashed passwords, sessions), an Admin dashboard, and a Student dashboard
showing attendance percentage, upcoming tests, and attended tests with scores.

## 1. Install requirements

You only need Flask itself — everything else (SQLite, password hashing) is
built into Python.

```bash
pip install flask
```

## 2. Create the database (run once)

```bash
python seed.py
```

This creates `instance/proctorai.db` and fills it with demo data:
- 1 admin account
- 5 student accounts (batch CSE-3B)
- 5 exams (3 in the past with results, 2 upcoming)
- A couple of sample violation logs

**Demo logins:**
| Role | Identifier | Password |
|---|---|---|
| Admin | `admin@proctorai.edu` | `admin123` |
| Student | `23C31A05F3` | `student123` |

## 3. Run the server

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser. It redirects to `/login`.

## 4. Project structure

```
proctorai/
  app.py                     Flask routes (auth, admin, student)
  schema.sql                 Database table definitions
  seed.py                    Creates + fills the database with demo data
  instance/
    proctorai.db             SQLite database file (created by seed.py)
  templates/
    login.html                Combined admin/student login
    admin_dashboard.html      Students / Exams / Logs / Results (Jinja, real data)
    student_dashboard.html    Attendance %, upcoming tests, attended tests
  static/
    css/style.css              Shared design tokens + component styles
```

## 5. How the login connects to the dashboards (the part you asked about)

`app.py` → `/login` route:
1. Reads `role`, `identifier`, `password` from the submitted form
2. Looks up the matching user in the `users` table
3. Checks the password against the **hashed** password using
   `werkzeug.security.check_password_hash` (never stores or compares plain text)
4. If it matches: stores `user_id` and `role` in the Flask `session`, then
   redirects to `/admin/dashboard` or `/student/dashboard`
5. If it does NOT match: re-renders `login.html` with an error message and
   does **not** redirect

Every dashboard route is protected by the `@login_required(role=...)` decorator
in `app.py` — if someone tries to visit `/admin/dashboard` without being logged
in as an admin, they get redirected straight back to `/login`.

## 6. How the Student Dashboard attendance percentage is calculated

In `app.py`, the `student_dashboard()` route:

```python
total_assigned = len(all_exams)          # every exam assigned to this student's batch
attended_count = len(results)            # how many the student has actually submitted
attendance_pct = round((attended_count / total_assigned) * 100)
```

Upcoming tests = exams for this batch that are scheduled in the future **and**
don't already have a result for this student.

## 7. What's still a mockup / what to build next

This backend covers **auth + dashboards with real data**. It does NOT yet include:
- The actual AI proctoring modules (Face Detection, Eye Tracking, Head Pose,
  Object Detection via YOLO, Audio Monitoring) — those need OpenCV/YOLO wired
  into a live webcam feed, per your abstract
- Live monitoring on the admin side (currently just static data tables — the
  earlier `admin_side.html` mockup had the live camera-feed grid; that needs
  WebRTC + Socket.io to actually stream video and push real-time alerts)
- The actual student exam-taking interface (questions, timer, answer saving) —
  the earlier `student_side.html` mockup has the UI; it isn't wired to the
  database yet
- Sign-up / account creation route (currently only seeded via `seed.py`)

Ask for any of these next and they can be built the same way — as real routes
backed by the same database.

---

## ID verification & camera selection (added)

**How identity is checked now (no more tick-box):**
1. Admin → **Students → Register photo** (one clear, front-facing photo per student).
   The admin's browser computes a 128-number "face fingerprint" and stores it with the photo.
2. At the System Check, the student's browser computes a fingerprint from the live camera and
   sends it to the server. **The server** compares it with the stored one (`FACE_MATCH_THRESHOLD`
   in `app.py`, default 0.5). The student never receives the stored fingerprint, and `/verify`
   refuses to open the exam unless the server itself recorded a match.
3. A wrong face is logged under **Activity Logs** as "Identity Verification" (High) with a snapshot.
   5 failures within 15 minutes locks the attempt.

Students with no registered photo are blocked with a clear message. For quick solo testing you can set
`ALLOW_FIRST_USE_ENROLLMENT = True` in `app.py` (first live capture becomes the reference). Keep it
`False` for real exams.

**Camera picker:** the System Check lists every camera, prefers the laptop's built-in one over
phone/virtual cameras (Phone Link, Camo, DroidCam, OBS...), remembers the choice for the exam page, and
explains black / frozen / no-face pictures.

**Needs internet** (face-api.js and its models load from jsDelivr; ~7 MB the first time).
Limits: this is face *matching*, not liveness detection - a printed photo or a screen showing the
student's photo could fool it. Treat it as one layer alongside the live monitoring.
=======
# Proctor-AI
>>>>>>> ca3616062b3f971262e0e787afb892ecf660b7d7
