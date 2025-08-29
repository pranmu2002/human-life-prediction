import os
import datetime
from flask import Flask, render_template, redirect, url_for, request, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_secret")

# Allow Render/Heroku-style DATABASE_URL, fall back to local SQLite
db_url = os.getenv("DATABASE_URL", "sqlite:///life_predictor.db")
# SQLAlchemy 2.x requires postgresql:// (not postgres://)
db_url = db_url.replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ----------------- MODELS -----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    predicted_life_expectancy = db.Column(db.Float)
    years_left = db.Column(db.Float)
    days_left = db.Column(db.Integer)

    user = db.relationship("User", backref=db.backref("predictions", lazy=True))

# ----------------- HELPERS -----------------
def predict_life(data):
    """Simple heuristic for demo only (not medical advice)."""
    base_expectancy = 80

    age = int(data["age"])
    bmi = float(data["bmi"])
    diabetic = data["diabetic"] == "true"
    systolic_bp = int(data["systolic_bp"])
    smoker = data["smoker"] == "true"
    sleep = float(data["daily_sleep_hours"])
    exercise = int(data["weekly_exercise_minutes"])
    alcohol = int(data["alcohol_units_per_week"])
    fruits = int(data["fruits_veg_servings_per_day"])
    stress = int(data["stress_level"])
    cholesterol = int(data["cholesterol"])

    if diabetic: base_expectancy -= 5
    if smoker: base_expectancy -= 7
    if bmi < 18 or bmi > 30: base_expectancy -= 3
    if systolic_bp > 140: base_expectancy -= 4
    if sleep < 6 or sleep > 9: base_expectancy -= 2
    if exercise > 150: base_expectancy += 2
    if alcohol > 14: base_expectancy -= 3
    if fruits >= 5: base_expectancy += 2
    if stress > 7: base_expectancy -= 2
    if cholesterol > 240: base_expectancy -= 3

    years_left = max(base_expectancy - age, 0)
    days_left = int(years_left * 365)
    return base_expectancy, years_left, days_left

def get_current_user():
    uid = session.get("user_id")
    return User.query.get(uid) if uid else None

# Make `session` and a lightweight `user_name` available to all templates
@app.context_processor
def inject_globals():
    user = get_current_user()
    return {
        "user_name": user.name if user else None,
        "is_admin": user.is_admin if user else False
    }

# ----------------- ROUTES -----------------
@app.route("/")
def index():
    # Use your existing templates/index.html
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not name or not email or not password:
            flash("All fields are required", "error")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("Email already registered", "error")
            return redirect(url_for("register"))

        hashed_pw = generate_password_hash(password)
        user = User(name=name, email=email, password=hashed_pw)
        db.session.add(user)
        db.session.commit()
        flash("Registration successful, please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        # Fixed admin shortcut
        if email == "swagatoroy2002@gmail.com" and password == "moyu2002":
            admin = User.query.filter_by(email=email).first()
            if not admin:
                admin = User(
                    name="pran",
                    email=email,
                    password=generate_password_hash(password),
                    is_admin=True
                )
                db.session.add(admin)
                db.session.commit()
            session["user_id"] = admin.id
            return redirect(url_for("dashboard"))

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            return redirect(url_for("dashboard"))

        flash("Invalid credentials", "error")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("Logged out successfully", "success")
    return redirect(url_for("index"))

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        expectancy, years_left, days_left = predict_life(request.form)
        prediction = Prediction(
            user_id=user.id,
            predicted_life_expectancy=expectancy,
            years_left=years_left,
            days_left=days_left
        )
        db.session.add(prediction)
        db.session.commit()
        flash("Prediction saved!", "success")
        return redirect(url_for("dashboard"))

    predictions = (
        Prediction.query
        .filter_by(user_id=user.id)
        .order_by(Prediction.created_at.desc())
        .all()
    )
    return render_template("dashboard.html", predictions=predictions)

@app.route("/download/<int:pid>")
def download(pid):
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))

    pred = Prediction.query.get_or_404(pid)
    if pred.user_id != user.id:
        flash("Unauthorized", "error")
        return redirect(url_for("dashboard"))

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.drawString(100, 750, "Life Prediction Report")
    pdf.drawString(100, 720, f"Life Expectancy: {pred.predicted_life_expectancy:.1f} years")
    pdf.drawString(100, 700, f"Years left: {pred.years_left:.1f}")
    pdf.drawString(100, 680, f"Days left: {pred.days_left}")
    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="prediction.pdf",
        mimetype="application/pdf"
    )

# ----------------- INIT -----------------
with app.app_context():
    db.create_all()
    # ensure admin exists (optional safety)
    admin_email = "swagatoroy2002@gmail.com"
    admin = User.query.filter_by(email=admin_email).first()
    if not admin:
        admin = User(
            name="pran",
            email=admin_email,
            password=generate_password_hash("moyu2002"),
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()

if __name__ == "__main__":
    # Don’t run debug=True in production; Render will set PORT.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
