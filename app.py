from flask import Flask, render_template, request, redirect, session
import sqlite3, random, time, os
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = "cloud-attendance-secret"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

DEFAULT_CLASS_CODE = "IT123"

# ---------------- DATABASE ----------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()

    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        email TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        role TEXT CHECK(role IN ('admin','teacher','student')),
        name TEXT
    )
    """)

    # DEFAULT ADMIN
    cur.execute("""
    INSERT OR IGNORE INTO users (email, password, role, name)
    VALUES ('admin@cloud.com', 'admin123', 'admin', 'Admin')
    """)

    # CLASSES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        dept TEXT NOT NULL,
        class_code TEXT UNIQUE NOT NULL
    )
    """)

    # DEFAULT CLASS
    cur.execute("""
    INSERT OR IGNORE INTO classes (name, dept, class_code)
    VALUES ('IT-A', 'IT', ?)
    """, (DEFAULT_CLASS_CODE,))

    # CLASS SCHEDULE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS class_schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER,
        day TEXT,
        start_time TEXT,
        end_time TEXT,
        FOREIGN KEY (class_id) REFERENCES classes(id)
    )
    """)

    # STUDENT PROFILE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS student_profile (
        email TEXT PRIMARY KEY,
        class_id INTEGER,
        FOREIGN KEY (email) REFERENCES users(email),
        FOREIGN KEY (class_id) REFERENCES classes(id)
    )
    """)

    # TEACHER PROFILE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS teacher_profile (
        email TEXT PRIMARY KEY,
        dept TEXT,
        FOREIGN KEY (email) REFERENCES users(email)
    )
    """)

    # TEACHER → CLASS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS teacher_class (
        email TEXT,
        class_id INTEGER,
        PRIMARY KEY (email, class_id),
        FOREIGN KEY (email) REFERENCES users(email),
        FOREIGN KEY (class_id) REFERENCES classes(id)
    )
    """)

    # ATTENDANCE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT,
        class_id INTEGER,
        timestamp INTEGER,
        FOREIGN KEY (email) REFERENCES users(email),
        FOREIGN KEY (class_id) REFERENCES classes(id)
    )
    """)

    # OTP
    cur.execute("""
    CREATE TABLE IF NOT EXISTS otp (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT,
        class_id INTEGER,
        created_time INTEGER,
        created_by TEXT,
        FOREIGN KEY (class_id) REFERENCES classes(id),
        FOREIGN KEY (created_by) REFERENCES users(email)
    )
    """)

    # Seed schedule for default class only once
    cur.execute("SELECT id FROM classes WHERE class_code=?", (DEFAULT_CLASS_CODE,))
    c = cur.fetchone()
    if c:
        class_id = c["id"]
        cur.execute("SELECT COUNT(*) as cnt FROM class_schedule WHERE class_id=?", (class_id,))
        cnt = cur.fetchone()["cnt"]
        if cnt == 0:
            cur.executemany("""
                INSERT INTO class_schedule (class_id, day, start_time, end_time)
                VALUES (?, ?, ?, ?)
            """, [
                (class_id, "Monday", "09:00", "10:00"),
                (class_id, "Wednesday", "11:00", "12:00"),
                (class_id, "Friday", "14:00", "15:00"),
            ])

    conn.commit()
    conn.close()

init_db()

# ---------------- HELPERS ----------------
def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "email" not in session:
                return redirect("/")
            if role and session.get("role") != role:
                return redirect("/")
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# ---------------- LOGIN ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        role = request.form["role"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT email, role FROM users WHERE email=? AND password=? AND role=?",
            (email, password, role)
        )
        user = cur.fetchone()
        conn.close()

        if user:
            session["email"] = user["email"]
            session["role"] = user["role"]
            return redirect(f"/{role}")

        return render_template("login.html", error="Invalid credentials",
                               title="Login", header="Login", subheader="Access your account")

    return render_template("login.html",
                           title="Login", header="Login", subheader="Access your account")

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        role = request.form["role"]
        name = request.form["name"].strip()

        class_code = (request.form.get("class_code") or "").strip().upper()
        dept = (request.form.get("dept") or "").strip()

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT email FROM users WHERE email=?", (email,))
        if cur.fetchone():
            conn.close()
            return render_template("register.html", error="User exists",
                                   title="Register", header="Create Account", subheader="Join Cloud Attendance")

        cur.execute(
            "INSERT INTO users (email, password, role, name) VALUES (?, ?, ?, ?)",
            (email, password, role, name)
        )

        if role == "student":
            if not class_code:
                conn.rollback(); conn.close()
                return render_template("register.html", error="Class code required for students",
                                       title="Register", header="Create Account", subheader="Join Cloud Attendance")

            cur.execute("SELECT id FROM classes WHERE class_code=?", (class_code,))
            class_row = cur.fetchone()
            if not class_row:
                conn.rollback(); conn.close()
                return render_template("register.html", error="Invalid class code",
                                       title="Register", header="Create Account", subheader="Join Cloud Attendance")

            cur.execute("INSERT INTO student_profile (email, class_id) VALUES (?, ?)",
                        (email, class_row["id"]))

        if role == "teacher":
            if not dept:
                conn.rollback(); conn.close()
                return render_template("register.html", error="Department required for teachers",
                                       title="Register", header="Create Account", subheader="Join Cloud Attendance")

            cur.execute("INSERT INTO teacher_profile (email, dept) VALUES (?, ?)",
                        (email, dept))

            # Assign teacher to default class initially
            cur.execute("""
            INSERT OR IGNORE INTO teacher_class (email, class_id)
            SELECT ?, id FROM classes WHERE class_code=?
            """, (email, DEFAULT_CLASS_CODE))

        conn.commit()
        conn.close()
        return redirect("/")

    return render_template("register.html",
                           title="Register", header="Create Account", subheader="Join Cloud Attendance")

# ---------------- ADMIN DASHBOARD ----------------
@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT a.email, u.name as student_name, c.name as class_name, c.class_code, a.timestamp
        FROM attendance a
        LEFT JOIN users u ON u.email = a.email
        LEFT JOIN classes c ON c.id = a.class_id
        ORDER BY a.timestamp DESC
        LIMIT 200
    """)
    rows = cur.fetchall()
    conn.close()

    records = [{
        "email": r["email"],
        "student_name": r["student_name"] or "-",
        "class_name": r["class_name"] or "-",
        "class_code": r["class_code"] or "-",
        "time": datetime.fromtimestamp(r["timestamp"]).strftime("%d-%b-%Y %I:%M %p")
    } for r in rows]

    return render_template("admin.html", records=records,
                           title="Admin", header="Admin Dashboard", subheader="Monitor attendance activity")

# ---------------- ADMIN: CLASSES ----------------
@app.route("/admin/classes", methods=["GET", "POST"])
@login_required("admin")
def admin_classes():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        name = request.form["name"].strip()
        dept = request.form["dept"].strip()
        class_code = request.form["class_code"].strip().upper()

        try:
            cur.execute(
                "INSERT INTO classes (name, dept, class_code) VALUES (?, ?, ?)",
                (name, dept, class_code)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            cur.execute("SELECT * FROM classes ORDER BY dept, name")
            classes = cur.fetchall()
            conn.close()
            return render_template(
                "admin_classes.html",
                classes=classes,
                error="Class code already exists!",
                title="Admin", header="Manage Classes", subheader="Create classes and manage schedule"
            )

    cur.execute("SELECT * FROM classes ORDER BY dept, name")
    classes = cur.fetchall()
    conn.close()

    return render_template(
        "admin_classes.html",
        classes=classes,
        title="Admin", header="Manage Classes", subheader="Create classes and manage schedule"
    )

# ---------------- ADMIN: SCHEDULE ----------------
@app.route("/admin/schedule/<int:class_id>", methods=["GET", "POST"])
@login_required("admin")
def admin_schedule(class_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM classes WHERE id=?", (class_id,))
    c = cur.fetchone()
    if not c:
        conn.close()
        return "Class not found", 404

    if request.method == "POST":
        day = request.form["day"].strip()
        start_time = request.form["start_time"].strip()
        end_time = request.form["end_time"].strip()

        cur.execute("""
            INSERT INTO class_schedule (class_id, day, start_time, end_time)
            VALUES (?, ?, ?, ?)
        """, (class_id, day, start_time, end_time))
        conn.commit()

    cur.execute("""
        SELECT day, start_time, end_time
        FROM class_schedule
        WHERE class_id=?
        ORDER BY
          CASE day
            WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3
            WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6
            WHEN 'Sunday' THEN 7 ELSE 8
          END, start_time
    """, (class_id,))
    schedule = cur.fetchall()

    conn.close()
    return render_template(
        "admin_schedule.html",
        c=c, schedule=schedule,
        title="Admin", header="Manage Schedule", subheader="Add weekly timings"
    )

# ---------------- ADMIN: ASSIGN TEACHERS ----------------
@app.route("/admin/teachers", methods=["GET", "POST"])
@login_required("admin")
def admin_teachers():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        teacher_email = request.form["teacher_email"].strip().lower()
        class_id = request.form["class_id"].strip()

        cur.execute("SELECT email FROM users WHERE email=? AND role='teacher'", (teacher_email,))
        if not cur.fetchone():
            cur.execute("SELECT * FROM classes ORDER BY dept, name")
            classes = cur.fetchall()
            cur.execute("""
                SELECT u.name, u.email, tp.dept
                FROM users u
                LEFT JOIN teacher_profile tp ON tp.email=u.email
                WHERE u.role='teacher'
                ORDER BY u.name
            """)
            teachers = cur.fetchall()
            conn.close()
            return render_template(
                "admin_teachers.html",
                classes=classes, teachers=teachers,
                error="Teacher not found. Register teacher first.",
                title="Admin", header="Assign Teachers", subheader="Attach teachers to classes"
            )

        cur.execute("""
            INSERT OR IGNORE INTO teacher_class (email, class_id)
            VALUES (?, ?)
        """, (teacher_email, class_id))
        conn.commit()

    cur.execute("SELECT * FROM classes ORDER BY dept, name")
    classes = cur.fetchall()

    cur.execute("""
        SELECT u.name, u.email, tp.dept
        FROM users u
        LEFT JOIN teacher_profile tp ON tp.email=u.email
        WHERE u.role='teacher'
        ORDER BY u.name
    """)
    teachers = cur.fetchall()

    conn.close()
    return render_template(
        "admin_teachers.html",
        classes=classes, teachers=teachers,
        title="Admin", header="Assign Teachers", subheader="Attach teachers to classes"
    )

# ---------------- TEACHER DASHBOARD ----------------
@app.route("/teacher")
@login_required("teacher")
def teacher_dashboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.name, c.dept, c.class_code
        FROM teacher_class tc
        JOIN classes c ON c.id = tc.class_id
        WHERE tc.email=?
        ORDER BY c.name
    """, (session["email"],))
    classes = cur.fetchall()
    conn.close()

    return render_template("teacher.html",
                           classes=classes,
                           otp=None,
                           title="Teacher", header="Teacher Dashboard", subheader="Generate OTP for your class")

@app.route("/teacher/profile")
@login_required("teacher")
def teacher_profile_page():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT email, name FROM users WHERE email=?", (session["email"],))
    user = cur.fetchone()

    cur.execute("SELECT dept FROM teacher_profile WHERE email=?", (session["email"],))
    prof = cur.fetchone()

    conn.close()
    return render_template("teacher_profile.html", user=user, prof=prof,
                           title="Teacher Profile", header="Teacher Profile", subheader="Your details")

@app.route("/teacher/classes")
@login_required("teacher")
def teacher_classes_page():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT c.id, c.name, c.dept, c.class_code
        FROM teacher_class tc
        JOIN classes c ON c.id = tc.class_id
        WHERE tc.email=?
        ORDER BY c.name
    """, (session["email"],))
    classes = cur.fetchall()

    selected_class_id = request.args.get("class_id")
    students = []
    selected_class = None

    if selected_class_id:
        cur.execute("SELECT * FROM classes WHERE id=?", (selected_class_id,))
        selected_class = cur.fetchone()

        cur.execute("""
            SELECT u.name, u.email
            FROM student_profile sp
            JOIN users u ON u.email = sp.email
            WHERE sp.class_id=?
            ORDER BY u.name
        """, (selected_class_id,))
        students = cur.fetchall()

    conn.close()

    return render_template("teacher_classes.html",
                           classes=classes,
                           selected_class=selected_class,
                           students=students,
                           title="My Classes", header="My Classes", subheader="Classes and enrolled students")

# ---------------- STUDENT DASHBOARD ----------------
@app.route("/student")
@login_required("student")
def student_dashboard():
    return render_template("student.html",
                           title="Student", header="Student Dashboard", subheader="Mark attendance using OTP")

@app.route("/student/profile")
@login_required("student")
def student_profile_page():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT email, name FROM users WHERE email=?", (session["email"],))
    user = cur.fetchone()

    cur.execute("""
        SELECT c.name as class_name, c.dept, c.class_code
        FROM student_profile sp
        JOIN classes c ON c.id = sp.class_id
        WHERE sp.email=?
    """, (session["email"],))
    class_info = cur.fetchone()

    conn.close()

    return render_template("student_profile.html",
                           user=user, class_info=class_info,
                           title="Student Profile", header="Student Profile", subheader="Your details")

@app.route("/student/schedule")
@login_required("student")
def student_schedule_page():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT class_id FROM student_profile WHERE email=?", (session["email"],))
    sp = cur.fetchone()
    if not sp:
        conn.close()
        return "Student not enrolled", 400

    cur.execute("""
        SELECT day, start_time, end_time
        FROM class_schedule
        WHERE class_id=?
        ORDER BY
          CASE day
            WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3
            WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6
            WHEN 'Sunday' THEN 7 ELSE 8
          END, start_time
    """, (sp["class_id"],))
    schedule = cur.fetchall()
    conn.close()

    return render_template("student_schedule.html",
                           schedule=schedule,
                           title="Schedule", header="Class Schedule", subheader="Your timetable")

@app.route("/student/attendance")
@login_required("student")
def student_attendance_page():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT a.timestamp, c.name as class_name, c.class_code
        FROM attendance a
        LEFT JOIN classes c ON c.id = a.class_id
        WHERE a.email=?
        ORDER BY a.timestamp DESC
        LIMIT 200
    """, (session["email"],))
    rows = cur.fetchall()
    conn.close()

    records = [{
        "class": f"{(r['class_name'] or '-') } ({(r['class_code'] or '-')})",
        "time": datetime.fromtimestamp(r["timestamp"]).strftime("%d-%b-%Y %I:%M %p")
    } for r in rows]

    return render_template("student_attendance.html",
                           records=records,
                           title="Attendance", header="Attendance History", subheader="Your logs")

# ---------------- OTP (Teacher) ----------------
@app.route("/generate_otp", methods=["POST"])
@login_required("teacher")
def generate_otp():
    email = session["email"]
    otp_code = str(random.randint(100000, 999999))
    ts = int(time.time())

    class_id = request.form.get("class_id")
    if not class_id:
        return redirect("/teacher")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM teacher_class WHERE email=? AND class_id=?", (email, class_id))
    if not cur.fetchone():
        conn.close()
        return "Not assigned to this class", 403

    cur.execute("DELETE FROM otp WHERE class_id=?", (class_id,))
    cur.execute("""
        INSERT INTO otp (code, class_id, created_time, created_by)
        VALUES (?, ?, ?, ?)
    """, (otp_code, class_id, ts, email))
    conn.commit()

    cur.execute("""
        SELECT c.id, c.name, c.dept, c.class_code
        FROM teacher_class tc
        JOIN classes c ON c.id = tc.class_id
        WHERE tc.email=?
        ORDER BY c.name
    """, (email,))
    classes = cur.fetchall()
    conn.close()

    return render_template("teacher.html",
                           classes=classes,
                           otp=otp_code,
                           title="Teacher", header="Teacher Dashboard", subheader="Generate OTP for your class")

# ---------------- OTP Submit (Student) ----------------
@app.route("/submit_otp", methods=["POST"])
@login_required("student")
def submit_otp():
    entered_otp = request.form["otp"].strip()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT class_id FROM student_profile WHERE email=?", (session["email"],))
    student = cur.fetchone()
    if not student:
        conn.close()
        return "Student not enrolled", 400

    cur.execute("""
        SELECT code, created_time FROM otp
        WHERE class_id=?
        ORDER BY created_time DESC
        LIMIT 1
    """, (student["class_id"],))
    otp_row = cur.fetchone()

    if otp_row:
        valid = (
            entered_otp == otp_row["code"]
            and int(time.time()) - otp_row["created_time"] <= 60
        )
        if valid:
            cur.execute("""
                INSERT INTO attendance (email, class_id, timestamp)
                VALUES (?, ?, ?)
            """, (session["email"], student["class_id"], int(time.time())))
            conn.commit()
            conn.close()
            return render_template("student.html", success=True,
                                   title="Student", header="Student Dashboard", subheader="Marked successfully")

    conn.close()
    return render_template("student.html", error=True,
                           title="Student", header="Student Dashboard", subheader="Invalid/Expired OTP")

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------------- MAIN ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
