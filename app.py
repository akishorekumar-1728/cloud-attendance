from flask import Flask, render_template, request
import sqlite3, random, time, os

app = Flask(__name__)

DB_PATH = "database.db"

# ---------- DATABASE ----------
def get_db():
    return sqlite3.connect(DB_PATH)

def create_tables():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS otp (
        code TEXT,
        created_time INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        student_email TEXT,
        timestamp INTEGER
    )
    """)

    conn.commit()
    conn.close()

create_tables()

# ---------- LOGIN ----------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form["role"]
        email = request.form["email"]

        if role == "admin":
            return render_template("admin.html")
        elif role == "teacher":
            return render_template("teacher.html")
        elif role == "student":
            return render_template("student.html", email=email)

    return render_template("login.html")

# ---------- OTP ----------
@app.route("/generate_otp", methods=["POST"])
def generate_otp():
    otp = str(random.randint(100000, 999999))
    ts = int(time.time())

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM otp")
    cur.execute("INSERT INTO otp VALUES (?, ?)", (otp, ts))
    conn.commit()
    conn.close()

    return f"OTP Generated: {otp} (valid 60 seconds)"

# ---------- STUDENT SUBMIT ----------
@app.route("/submit_otp", methods=["POST"])
def submit_otp():
    otp = request.form["otp"]
    email = request.form["email"]

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT code, created_time FROM otp")
    data = cur.fetchone()

    if data:
        db_otp, created = data
        if otp == db_otp and int(time.time()) - created <= 30:
            cur.execute(
                "INSERT INTO attendance VALUES (?, ?)",
                (email, int(time.time()))
            )
            conn.commit()
            conn.close()
            return "Attendance Marked ✅"

    conn.close()
    return "Invalid or Expired OTP ❌"

# ---------- VIEW ATTENDANCE ----------
@app.route("/view_attendance")
def view_attendance():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM attendance")
    data = cur.fetchall()
    conn.close()
    return render_template("admin.html", records=data)

# ---------- MAIN ----------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",   # IMPORTANT FOR DOCKER & AZURE
        port=5000,
        debug=False
    )
