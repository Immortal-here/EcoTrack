
from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "data", "ecotrack.db")

app = Flask(__name__)
app.secret_key = "change_this_secret_key"

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
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
    con.commit()
    con.close()

EMISSION = {
    "travel": {"car":0.12, "bus":0.07, "bike":0.05, "cycle":0.0, "walk":0.0},
    "electricity_kwh": 0.82,
    "diet": {"veg":1.7, "nonveg":3.5}
}
def compute_co2(travel_mode, travel_km, electricity_kwh, diet_type):
    travel = EMISSION["travel"].get(travel_mode, 0) * travel_km
    power = EMISSION["electricity_kwh"] * electricity_kwh
    diet = EMISSION["diet"].get(diet_type, 0)
    return travel + power + diet

@app.before_request
def ensure_db():
    if not os.path.exists(DB_PATH):
        init_db()

@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("home.html", title="EcoTrack – Home")

from werkzeug.security import generate_password_hash

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
            hashed_pw = generate_password_hash(password, method="pbkdf2:sha256")  # ✅ force method
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

from werkzeug.security import check_password_hash

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

        # ✅ check password hash properly
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            flash("Welcome, " + user["name"] + "!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid credentials.", "warning")

    return render_template("login.html", title="Login")

@app.route("/logout")
def logout():
    session.clear(); flash("You have been logged out.", "success")
    return redirect(url_for("home"))

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
        con = get_db(); cur = con.cursor()
        cur.execute(
            "INSERT INTO activities (user_id, date, travel_mode, travel_km, electricity_kwh, diet_type, co2_kg) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session["user_id"], date_str, travel_mode, travel_km, electricity_kwh, diet_type, co2_kg)
        )
        con.commit(); con.close()
        flash("Activity saved. Estimated CO₂: {:.2f} kg".format(co2_kg), "success")
        return redirect(url_for("dashboard"))
    default_date = date.today().isoformat()
    return render_template("input.html", title="Add Activity", default_date=default_date)

@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM activities WHERE user_id=? ORDER BY date DESC", (session["user_id"],))
    rows = cur.fetchall()
    con.close()

    # --- Line Chart (7-day trend) ---
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

    # --- Pie Chart (breakdown) ---
    travel = sum(r["co2_kg"] for r in rows if r["travel_mode"] not in ["", "Electricity"])
    electricity = sum(r["co2_kg"] for r in rows if r["electricity_kwh"] > 0)
    diet = sum(r["co2_kg"] for r in rows if r["diet_type"] in ["Veg", "Non-Veg"])

    entries = [dict(r) for r in rows]

    return render_template("dashboard.html",
                           title="Dashboard",
                           entries=entries,
                           chart_labels=labels,
                           chart_values=values,
                           travel=travel,
                           electricity=electricity,
                           diet=diet)


if __name__ == "__main__":
    print("EcoTrack starting on http://127.0.0.1:5000")
    app.run(debug=True)
