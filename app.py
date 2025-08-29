import os
import smtplib
import ssl
import random
import string
from datetime import datetime, timedelta
from email.message import EmailMessage
from io import BytesIO

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, send_file
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, login_user, logout_user, current_user,
    login_required, UserMixin
)
from werkzeug.security import generate_password_hash, check_password_hash

# ------- Load environment (optional locally) -------
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ------- App setup -------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///life.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email config
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USER = os.environ.get('EMAIL_USER')  # must be set in Render
EMAIL_PASS = os.environ.get('EMAIL_PASS')  # must be set in Render
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'true').lower() == 'true'

# Prediction baseline
BASE_LIFE_EXPECTANCY = 78

# Extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ---------- Models ----------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    age = db.Column(db.Integer, nullable=False)
    sex = db.Column(db.String(10), nullable=False)
    bmi = db.Column(db.Float, nullable=True)
    diabetic = db.Column(db.Boolean, default=False)
    systolic_bp = db.Column(db.Integer, nullable=True)
    smoker = db.Column(db.Boolean, default=False)
    daily_sleep_hours = db.Column(db.Float, nullable=True)
    weekly_exercise_minutes = db.Column(db.Integer, nullable=True)
    alcohol_units_per_week = db.Column(db.Integer, nullable=True)
    fruits_veg_servings_per_day = db.Column(db.Integer, nullable=True)
    stress_level = db.Column(db.Integer, nullable=True)
    cholesterol = db.Column(db.Integer, nullable=True)

    predicted_life_expectancy = db.Column(db.Float, nullable=False)
    years_left = db.Column(db.Float, nullable=False)
    days_left = db.Column(db.Integer, nullable=False)

class PasswordReset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(6), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None

# ---------- Helpers ----------
def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def make_code(n=6):
    return ''.join(random.choices(string.digits, k=n))

def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send email via SMTP. If creds missing, log to console and return True (dev-friendly)."""
    if not (EMAIL_USER and EMAIL_PASS):
        print("[EMAIL DEV MODE] Missing EMAIL_USER/EMAIL_PASS; printing instead:")
        print(f"TO: {to_email}\nSUBJECT: {subject}\n\n{body}")
        return True
    try:
        msg = EmailMessage()
        msg['From'] = EMAIL_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.set_content(body)
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            if EMAIL_USE_TLS:
                context = ssl.create_default_context()
                server.starttls(context=context)
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        return True
    except Exception as e:
        print("Email send error:", e)
        return False

def normalize_bool(v):
    return str(v).lower() in ('1', 'true', 'on', 'yes')

def safe_int(v, default=0):
    try:
        return int(float(v))
    except Exception:
        return default

def safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default

def predict_life_expectancy(inputs: dict):
    """Heuristic model for educational purposes only."""
    age = safe_int(inputs.get('age'))
    sex = inputs.get('sex', 'other')
    bmi = safe_float(inputs.get('bmi'))
    diabetic = normalize_bool(inputs.get('diabetic'))
    systolic_bp = safe_int(inputs.get('systolic_bp'))
    smoker = normalize_bool(inputs.get('smoker'))
    sleep = safe_float(inputs.get('daily_sleep_hours'))
    exercise = safe_int(inputs.get('weekly_exercise_minutes'))
    alcohol = safe_int(inputs.get('alcohol_units_per_week'))
    fv = safe_int(inputs.get('fruits_veg_servings_per_day'))
    stress = clamp(safe_int(inputs.get('stress_level'), 5), 1, 10)
    chol = safe_int(inputs.get('cholesterol'), 180)

    score = BASE_LIFE_EXPECTANCY

    if sex == 'female':
        score += 3
    elif sex == 'male':
        score += 1

    if bmi:
        if bmi < 18.5: score -= 2
        elif 18.5 <= bmi < 25: score += 2
        elif 25 <= bmi < 30: score -= 1
        else: score -= 3

    if systolic_bp:
        if systolic_bp < 120: score += 1
        elif 120 <= systolic_bp <= 129: pass
        elif 130 <= systolic_bp <= 139: score -= 1
        elif 140 <= systolic_bp <= 159: score -= 3
        else: score -= 5

    if diabetic: score -= 5
    if smoker: score -= 7

    if sleep:
        if 6.5 <= sleep <= 8.5: score += 2
        else: score -= 2

    if exercise >= 150: score += 3
    elif exercise >= 60: score += 1
    else: score -= 1

    if alcohol == 0: score += 1
    elif 1 <= alcohol <= 7: pass
    elif 8 <= alcohol <= 14: score -= 1
    else: score -= 3

    if fv >= 5: score += 2
    elif fv >= 3: score += 1
    else: score -= 1

    score -= clamp(stress - 4, -3, 6) * 0.5

    if chol < 180: score += 1
    elif 180 <= chol <= 199: pass
    elif 200 <= chol <= 239: score -= 1
    else: score -= 2

    score = clamp(score, 50, 100)
    predicted_le = score
    years_left = max(0.0, predicted_le - age)
    days_left = int(years_left * 365)

    return {
        'predicted_life_expectancy': round(predicted_le, 1),
        'years_left': round(years_left, 1),
        'days_left': days_left,
    }

# -------- Simple login throttle (session-based) --------
def throttle_login():
    # Max 7 attempts per 10 minutes
    now = datetime.utcnow().timestamp()
    attempts = session.get('login_attempts', [])
    # keep only last 10 minutes
    attempts = [t for t in attempts if now - t < 600]
    if len(attempts) >= 7:
        return True
    attempts.append(now)
    session['login_attempts'] = attempts
    return False

# ---------- Routes ----------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''

        if not name or not email or not password:
            flash('All fields are required.', 'error')
            return redirect(url_for('register'))
        if '@' not in email or '.' not in email.split('@')[-1]:
            flash('Please enter a valid email.', 'error')
            return redirect(url_for('register'))
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered. Try logging in.', 'error')
            return redirect(url_for('login'))
        try:
            user = User(name=name, email=email, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            flash('Registration successful. Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('Could not create account. Please try again.', 'error')
            return redirect(url_for('register'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if throttle_login():
            flash('Too many attempts. Please wait a few minutes and try again.', 'error')
            return redirect(url_for('login'))

        email_or_name = (request.form.get('email_or_name') or '').strip()
        password = request.form.get('password') or ''

        user = None
        if '@' in email_or_name:
            user = User.query.filter_by(email=email_or_name.lower()).first()
        if user is None:
            user = User.query.filter_by(name=email_or_name).first()

        if user and check_password_hash(user.password_hash, password):
            session['login_attempts'] = []  # reset
            login_user(user, remember=True)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid email/name or password.', 'error')
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'success')
    return redirect(url_for('index'))

@app.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        if not email:
            flash('Please enter your email.', 'error')
            return redirect(url_for('forgot_password'))
        user = User.query.filter_by(email=email).first()
        if not user:
            # Do not reveal whether email exists
            flash('If the email exists, a code has been sent.', 'info')
            return redirect(url_for('forgot_password'))

        code = make_code(6)
        expires = datetime.utcnow() + timedelta(minutes=15)
        try:
            PasswordReset.query.filter_by(email=email).delete()
            db.session.add(PasswordReset(email=email, code=code, expires_at=expires))
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Server error. Please try again.', 'error')
            return redirect(url_for('forgot_password'))

        body = f"Your password reset code is: {code}\nIt expires at {expires} UTC (15 minutes)."
        if send_email(email, 'Your Password Reset Code', body):
            flash('Check your email for the 6-digit code.', 'success')
            return redirect(url_for('reset_password'))
        else:
            flash('Could not send email. Ask admin to configure SMTP.', 'error')
            return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html')

@app.route('/reset', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        code = (request.form.get('code') or '').strip()
        new_password = request.form.get('password') or ''

        if len(code) != 6 or not code.isdigit():
            flash('Invalid code format.', 'error')
            return redirect(url_for('reset_password'))
        if len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return redirect(url_for('reset_password'))

        pr = PasswordReset.query.filter_by(email=email, code=code).first()
        if not pr or pr.expires_at < datetime.utcnow():
            flash('Invalid or expired code.', 'error')
            return redirect(url_for('reset_password'))
        user = User.query.filter_by(email=email).first()
        if not user:
            flash('No user found for that email.', 'error')
            return redirect(url_for('reset_password'))

        try:
            user.password_hash = generate_password_hash(new_password)
            db.session.delete(pr)
            db.session.commit()
            flash('Password has been reset. Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception:
            db.session.rollback()
            flash('Server error. Please try again.', 'error')
            return redirect(url_for('reset_password'))
    return render_template('reset_password.html')

@app.route('/dashboard')
@login_required
def dashboard():
    preds = Prediction.query.filter_by(user_id=current_user.id).order_by(Prediction.created_at.desc()).all()
    return render_template('dashboard.html', predictions=preds)

@app.route('/predict', methods=['POST'])
@login_required
def predict():
    # Server-side validation
    required_fields = ['age','sex','bmi','systolic_bp','daily_sleep_hours','weekly_exercise_minutes','alcohol_units_per_week','fruits_veg_servings_per_day','stress_level','cholesterol']
    for f in required_fields:
        if not (request.form.get(f)):
            flash('Please fill in all required fields.', 'error')
            return redirect(url_for('dashboard'))

    inputs = {k: request.form.get(k) for k in request.form}
    result = predict_life_expectancy(inputs)

    try:
        pred = Prediction(
            user_id=current_user.id,
            age=safe_int(inputs['age']),
            sex=inputs['sex'],
            bmi=safe_float(inputs.get('bmi', 0)),
            diabetic=normalize_bool(inputs.get('diabetic')),
            systolic_bp=safe_int(inputs.get('systolic_bp', 0)),
            smoker=normalize_bool(inputs.get('smoker')),
            daily_sleep_hours=safe_float(inputs.get('daily_sleep_hours', 0)),
            weekly_exercise_minutes=safe_int(inputs.get('weekly_exercise_minutes', 0)),
            alcohol_units_per_week=safe_int(inputs.get('alcohol_units_per_week', 0)),
            fruits_veg_servings_per_day=safe_int(inputs.get('fruits_veg_servings_per_day', 0)),
            stress_level=safe_int(inputs.get('stress_level', 5)),
            cholesterol=safe_int(inputs.get('cholesterol', 180)),
            predicted_life_expectancy=result['predicted_life_expectancy'],
            years_left=result['years_left'],
            days_left=result['days_left']
        )
        db.session.add(pred)
        db.session.commit()
        flash('Prediction saved. You can download the PDF.', 'success')
    except Exception:
        db.session.rollback()
        flash('Could not save prediction. Please try again.', 'error')

    return redirect(url_for('dashboard'))

# PDF generation with ReportLab
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

@app.route('/download/<int:pred_id>')
@login_required
def download(pred_id):
    pred = Prediction.query.filter_by(id=pred_id, user_id=current_user.id).first()
    if not pred:
        flash('Prediction not found.', 'error')
        return redirect(url_for('dashboard'))

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 20)
    c.drawString(2*cm, height - 2*cm, "Life Prediction Report")
    c.setFont("Helvetica", 10)
    c.drawString(2*cm, height - 2.6*cm, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(2*cm, height - 3.4*cm, f"User: {current_user.name} ({current_user.email})")

    y = height - 4.2*cm
    c.setFont("Helvetica", 11)
    def line(label, value):
        nonlocal y
        c.drawString(2*cm, y, f"{label}: {value}")
        y -= 0.7*cm

    line("Age", pred.age)
    line("Sex", pred.sex)
    line("BMI", pred.bmi)
    line("Diabetic", 'Yes' if pred.diabetic else 'No')
    line("Systolic BP", pred.systolic_bp)
    line("Smoker", 'Yes' if pred.smoker else 'No')
    line("Daily Sleep (h)", pred.daily_sleep_hours)
    line("Weekly Exercise (min)", pred.weekly_exercise_minutes)
    line("Alcohol (units/week)", pred.alcohol_units_per_week)
    line("Fruits & Veg (servings/day)", pred.fruits_veg_servings_per_day)
    line("Stress (1-10)", pred.stress_level)
    line("Cholesterol (mg/dL)", pred.cholesterol)

    y -= 0.5*cm
    c.setFont("Helvetica-Bold", 12)
    line("Predicted Life Expectancy (years)", pred.predicted_life_expectancy)
    line("Years Left", pred.years_left)
    line("Days Left", pred.days_left)

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(2*cm, 1.8*cm, "This is a heuristic educational estimate, not medical advice.")

    c.showPage()
    c.save()
    buffer.seek(0)

    filename = f"life_prediction_{pred.id}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash('Admins only.', 'error')
        return redirect(url_for('dashboard'))
    users = User.query.order_by(User.id.desc()).all()
    preds = Prediction.query.order_by(Prediction.created_at.desc()).all()
    return render_template('admin.html', users=users, predictions=preds)

# ---------- Init DB & fixed admin ----------
@app.before_first_request
def init_db_and_admin():
    db.create_all()
    try:
        admin_email = 'swagatoroy2002@gmail.com'
        admin_name = 'pran'
        admin_password = 'moyu2002'
        admin = User.query.filter_by(email=admin_email).first()
        if not admin:
            admin = User(
                name=admin_name,
                email=admin_email,
                password_hash=generate_password_hash(admin_password),
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
    except Exception:
        db.session.rollback()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
