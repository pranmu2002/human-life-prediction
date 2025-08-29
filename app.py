import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# ---------------- CONFIG ----------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")

# Database config (SQLite by default, can switch to PostgreSQL if needed)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///users.db"
).replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ---------------- MODELS ----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)


# ---------------- EMAIL ----------------
def send_email(receiver, subject, body):
    try:
        smtp_host = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("EMAIL_PORT", 587))
        smtp_user = os.environ.get("EMAIL_USER")
        smtp_pass = os.environ.get("EMAIL_PASS")

        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = receiver
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, receiver, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print("Email error:", e)
        return False


# ---------------- LIFE PREDICTION ----------------
def predict_life_expectancy(data):
    base = 80
    base -= data.get("age", 0) * 0.2
    if data.get("diabetic"):
        base -= 8
    if data.get("blood_pressure") == "high":
        base -= 6
    if data.get("smoking"):
        base -= 10
    if data.get("sleep", 7) < 6:
        base -= 5
    if data.get("exercise", 0) < 3:
        base -= 4
    if data.get("alcohol"):
        base -= 6
    if data.get("junk_food"):
        base -= 3
    return max(30, round(base))


# ---------------- ROUTES ----------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        if User.query.filter_by(email=email).first():
            flash("Email already registered!", "danger")
            return redirect(url_for("register"))

        hashed_pw = generate_password_hash(password)
        new_user = User(name=name, email=email, password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()

        flash("Registration successful! Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            session["is_admin"] = user.is_admin
            session["name"] = user.name
            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password", "danger")
            return redirect(url_for("login"))
    return render_template("login.html")


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form["email"]
        user = User.query.filter_by(email=email).first()
        if not user:
            flash("Email not found", "danger")
            return redirect(url_for("forgot"))

        code = str(random.randint(1000, 9999))
        session["reset_code"] = code
        session["reset_email"] = email

        send_email(email, "Password Reset Code", f"Your reset code is {code}")
        flash("Reset code sent to your email", "info")
        return redirect(url_for("reset_password"))
    return render_template("forgot.html")


@app.route("/reset", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        code = request.form["code"]
        new_pw = request.form["password"]

        if code == session.get("reset_code"):
            email = session.get("reset_email")
            user = User.query.filter_by(email=email).first()
            if user:
                user.password_hash = generate_password_hash(new_pw)
                db.session.commit()
                flash("Password reset successful!", "success")
                return redirect(url_for("login"))
        flash("Invalid code!", "danger")
        return redirect(url_for("reset_password"))
    return render_template("reset.html")


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        data = {
            "age": int(request.form["age"]),
            "diabetic": request.form.get("diabetic") == "yes",
            "blood_pressure": request.form["blood_pressure"],
            "smoking": request.form.get("smoking") == "yes",
            "sleep": int(request.form["sleep"]),
            "exercise": int(request.form["exercise"]),
            "alcohol": request.form.get("alcohol") == "yes",
            "junk_food": request.form.get("junk_food") == "yes",
        }
        years_left = predict_life_expectancy(data)
        return render_template("result.html", years=years_left)

    return render_template("dashboard.html")


@app.route("/download/<int:years>")
def download(years):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.drawString(100, 750, f"Life Expectancy Prediction")
    p.drawString(100, 720, f"Estimated years left: {years}")
    p.save()

    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="prediction.pdf")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))


# ---------------- INIT DB & ADMIN ----------------
def init_db_and_admin():
    with app.app_context():
        db.create_all()
        try:
            admin_email = "swagatoroy2002@gmail.com"
            admin_name = "pran"
            admin_password = "moyu2002"
            admin = User.query.filter_by(email=admin_email).first()
            if not admin:
                admin = User(
                    name=admin_name,
                    email=admin_email,
                    password_hash=generate_password_hash(admin_password),
                    is_admin=True,
                )
                db.session.add(admin)
                db.session.commit()
        except Exception:
            db.session.rollback()


# ---------------- MAIN ----------------
if __name__ == "__main__":
    init_db_and_admin()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
