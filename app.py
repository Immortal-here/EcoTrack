from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, make_response
import sqlite3, os, io, csv
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime, timedelta
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "data", "ecotrack.db")

app = Flask(__name__)
app.secret_key = "change_this_secret_key"

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    # Safe to call multiple times: uses CREATE TABLE IF NOT EXISTS
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    con = get_db()
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            travel_mode TEXT NOT NULL,
            travel_km REAL NOT NULL,
            electricity_kwh REAL NOT NULL,
            diet_type TEXT NOT NULL,
            co2_kg REAL NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    # new table for per-user settings (weekly goal etc)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            weekly_goal REAL DEFAULT 20.0,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    con.commit()
    con.close()

# Emission constants & helper
EMISSION = {
    "travel": {"car":0.12, "bus":0.07, "bike":0.05, "cycle":0.0, "walk":0.0},
    "electricity_kwh": 0.82,
    "diet": {"veg":1.7, "nonveg":3.5}
}
def compute_co2(travel_mode, travel_km, electricity_kwh, diet_type):
    travel = EMISSION["travel"].get(travel_mode.lower(), 0) * travel_km
    power = EMISSION["electricity_kwh"] * electricity_kwh
    diet = EMISSION["diet"].get(diet_type.lower(), 0)
    return travel + power + diet

# Ensure DB schema exists on every request (safe)
@app.before_request
def ensure_db():
    init_db()

# ----- Settings helpers -----
def get_user_goal(user_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT weekly_goal FROM user_settings WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    return float(row["weekly_goal"]) if row else 20.0

def set_user_goal(user_id, goal):
    con = get_db(); cur = con.cursor()
    # insert or replace
    cur.execute("INSERT OR REPLACE INTO user_settings (user_id, weekly_goal) VALUES (?, ?)", (user_id, goal))
    con.commit(); con.close()

# ----- Routes -----
@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("home.html", title="EcoTrack – Home")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not name or not email or not password:
            flash("All fields are required.", "warning")
            return redirect(url_for("register"))

        con = get_db()
        cur = con.cursor()
        try:
            hashed_pw = generate_password_hash(password, method="pbkdf2:sha256")
            cur.execute(
                "INSERT INTO users (name,email,password_hash) VALUES(?,?,?)",
                (name, email, hashed_pw)
            )
            con.commit()
            flash("Registration successful. Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered.", "warning")
        finally:
            con.close()

    return render_template("register.html", title="Register")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT * FROM users WHERE email=?", (email,))
        user = cur.fetchone()
        con.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            flash("Welcome, " + user["name"] + "!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid credentials.", "warning")

    return render_template("login.html", title="Login")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))

# Create new activity
@app.route("/input", methods=["GET","POST"])
def input_activity():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    if request.method == "POST":
        date_str = request.form["date"]
        travel_mode = request.form["travel_mode"]
        travel_km = float(request.form["travel_km"] or 0)
        electricity_kwh = float(request.form["electricity_kwh"] or 0)
        diet_type = request.form["diet_type"]
        co2_kg = compute_co2(travel_mode, travel_km, electricity_kwh, diet_type)

        con = get_db()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO activities (user_id, date, travel_mode, travel_km, electricity_kwh, diet_type, co2_kg) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session["user_id"], date_str, travel_mode, travel_km, electricity_kwh, diet_type, co2_kg)
        )
        con.commit()
        con.close()

        flash("Activity saved. Estimated CO₂: {:.2f} kg".format(co2_kg), "success")
        return redirect(url_for("dashboard"))

    default_date = date.today().isoformat()
    return render_template("input.html", title="Add Activity", default_date=default_date, activity=None, edit=False)

# Edit activity (GET shows form prefilled; POST updates)
@app.route("/activity/edit/<int:act_id>", methods=["GET","POST"])
def edit_activity(act_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM activities WHERE id=? AND user_id=?", (act_id, session["user_id"]))
    row = cur.fetchone()
    if not row:
        con.close()
        flash("Activity not found or not authorized.", "warning")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        date_str = request.form["date"]
        travel_mode = request.form["travel_mode"]
        travel_km = float(request.form["travel_km"] or 0)
        electricity_kwh = float(request.form["electricity_kwh"] or 0)
        diet_type = request.form["diet_type"]
        co2_kg = compute_co2(travel_mode, travel_km, electricity_kwh, diet_type)

        cur.execute("""
            UPDATE activities
            SET date=?, travel_mode=?, travel_km=?, electricity_kwh=?, diet_type=?, co2_kg=?
            WHERE id=? AND user_id=?
        """, (date_str, travel_mode, travel_km, electricity_kwh, diet_type, co2_kg, act_id, session["user_id"]))
        con.commit()
        con.close()
        flash("Activity updated.", "success")
        return redirect(url_for("dashboard"))

    # GET -> render form with activity data
    activity = dict(row)
    con.close()
    return render_template("input.html", title="Edit Activity", default_date=activity["date"], activity=activity, edit=True)

# Delete activity (POST)
@app.route("/activity/delete/<int:act_id>", methods=["POST"])
def delete_activity(act_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM activities WHERE id=? AND user_id=?", (act_id, session["user_id"]))
    con.commit()
    con.close()
    flash("Activity deleted.", "success")
    return redirect(url_for("dashboard"))

# Settings: Set weekly goal (GET shows form; POST saves)
@app.route("/settings", methods=["GET","POST"])
def settings():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    user_id = session["user_id"]
    if request.method == "POST":
        try:
            goal = float(request.form["weekly_goal"])
            set_user_goal(user_id, goal)
            flash(f"Weekly goal updated to {goal} kg.", "success")
            return redirect(url_for("settings"))
        except ValueError:
            flash("Invalid value for goal.", "warning")
            return redirect(url_for("settings"))

    current_goal = get_user_goal(user_id)
    # optionally show how many activities exist
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM activities WHERE user_id=?", (user_id,))
    cnt = cur.fetchone()["cnt"]
    con.close()
    return render_template("settings.html", title="Settings", weekly_goal=current_goal, activity_count=cnt)

# Reset statistics (POST)
@app.route("/reset_stats", methods=["POST"])
def reset_stats():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM activities WHERE user_id=?", (session["user_id"],))
    con.commit()
    con.close()
    flash("All your activities have been deleted.", "success")
    return redirect(url_for("dashboard"))

# Dashboard (unchanged logic but uses user-specific goal)
@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM activities WHERE user_id=? ORDER BY date DESC", (session["user_id"],))
    rows = cur.fetchall()
    con.close()

    today = date.today()
    labels, values, daily = [], [], {}
    for r in rows:
        daily.setdefault(r["date"], 0.0)
        daily[r["date"]] += float(r["co2_kg"])
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        labels.append(ds)
        values.append(round(daily.get(ds, 0.0), 2))

    # breakdown totals (basic heuristic)
    travel = sum(r["co2_kg"] for r in rows if r["travel_mode"])
    electricity = sum(r["co2_kg"] for r in rows if r["electricity_kwh"] > 0)
    diet = sum(r["co2_kg"] for r in rows if r["diet_type"])

    total = travel + electricity + diet

    # use per-user goal
    weekly_goal = get_user_goal(session["user_id"])
    progress = min((total / weekly_goal) * 100, 100) if weekly_goal > 0 else 0

    # Badges / Achievements
    badges = []
    if total < 10:
        badges.append("🏅 Eco Saver – Excellent! Very low CO₂ emissions this week.")
    if total < weekly_goal:
        badges.append("🌟 Goal Achiever – You stayed under your weekly CO₂ goal!")
    if total >= weekly_goal and total > 0:
        badges.append("⚠️ Over Achiever – You exceeded the weekly CO₂ goal, aim lower next week.")

    entries = [dict(r) for r in rows]

    return render_template("dashboard.html",
                           title="Dashboard",
                           entries=entries,
                           chart_labels=labels,
                           chart_values=values,
                           travel=round(travel, 2),
                           electricity=round(electricity, 2),
                           diet=round(diet, 2),
                           total=round(total, 2),
                           goal=weekly_goal,
                           progress=round(progress, 2),
                           badges=badges)

# ------------------------
# Export CSV
# ------------------------
@app.route("/export_csv")
def export_csv():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT date, travel_mode, travel_km, electricity_kwh, diet_type, co2_kg FROM activities WHERE user_id=?", (session["user_id"],))
    rows = cur.fetchall()
    con.close()

    def generate():
        yield "Date,Travel Mode,Distance (KM),Electricity (kWh),Diet Type,CO₂ (kg)\n"
        for r in rows:
            yield f"{r['date']},{r['travel_mode']},{r['travel_km']},{r['electricity_kwh']},{r['diet_type']},{r['co2_kg']}\n"

    return Response(generate(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=activities.csv"})

# ------------------------
# Export PDF
# ------------------------
@app.route("/export_pdf")
def export_pdf():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT date, travel_mode, travel_km, electricity_kwh, diet_type, co2_kg FROM activities WHERE user_id=?", (session["user_id"],))
    rows = cur.fetchall()
    con.close()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()

    data = [["Date", "Travel Mode", "Distance (KM)", "Electricity (kWh)", "Diet Type", "CO₂ (kg)"]]
    for r in rows:
        data.append([r["date"], r["travel_mode"], r["travel_km"], r["electricity_kwh"], r["diet_type"], f"{r['co2_kg']:.2f}"])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.green),
        ('TEXTCOLOR',(0,0),(-1,0),colors.white),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 10),
        ('BACKGROUND',(0,1),(-1,-1),colors.whitesmoke),
        ('GRID',(0,0),(-1,-1),1,colors.black),
    ]))

    story = [Paragraph("EcoTrack - Activity Report", styles['Title']), table]
    doc.build(story)

    pdf = buffer.getvalue()
    buffer.close()

    response = make_response(pdf)
    response.headers["Content-Disposition"] = "attachment; filename=activities.pdf"
    response.mimetype = "application/pdf"
    return response

if __name__ == "__main__":
    print("EcoTrack starting on http://127.0.0.1:5000")
    app.run(debug=True)
