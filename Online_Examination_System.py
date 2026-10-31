!pip -q install flask
import sqlite3, threading
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, flash
from jinja2 import DictLoader
from werkzeug.security import generate_password_hash, check_password_hash

DB = "exam.db"

def q(sql, args=(), one=False, commit=False):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.execute(sql, args)
    if commit:
        con.commit()
        rid = cur.lastrowid
        con.close()
        return rid
    rows = cur.fetchall()
    con.close()
    return (rows[0] if rows else None) if one else rows

def init_db():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, password TEXT, role TEXT, registered_on TEXT, password_plain TEXT);
    CREATE TABLE IF NOT EXISTS exams(id INTEGER PRIMARY KEY, title TEXT, duration INTEGER, pass_pct INTEGER DEFAULT 40);
    CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, exam_id INTEGER, text TEXT,
        a TEXT, b TEXT, c TEXT, d TEXT, correct TEXT);
    CREATE TABLE IF NOT EXISTS results(id INTEGER PRIMARY KEY, user_id INTEGER, exam_id INTEGER,
        score INTEGER, total INTEGER, taken_on TEXT);
    """)
    cols = [r[1] for r in con.execute("PRAGMA table_info(users)")]
    if "registered_on" not in cols:          # upgrade old database
        con.execute("ALTER TABLE users ADD COLUMN registered_on TEXT")
    if "password_plain" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN password_plain TEXT")
    con.commit(); con.close()
    if not q("SELECT 1 FROM users WHERE role='admin'", one=True):
        q("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)",
          ("Admin", "admin@exam.com", generate_password_hash("admin123"), "admin"), commit=True)
    if not q("SELECT 1 FROM exams", one=True):   # demo data
        eid = q("INSERT INTO exams(title,duration,pass_pct) VALUES('Python Basics',5,40)", commit=True)
        demo = [("Which brackets are used to create a list in Python?", "()", "[]", "{}", "<>", "B"),
                ("Who created Python?", "Guido van Rossum", "James Gosling", "Dennis Ritchie", "Linus Torvalds", "A"),
                ("What is the output of len([1,2,3])?", "2", "4", "3", "Error", "C")]
        for t, a, b, c, d, cor in demo:
            q("INSERT INTO questions(exam_id,text,a,b,c,d,correct) VALUES(?,?,?,?,?,?,?)",
              (eid, t, a, b, c, d, cor), commit=True)

# ----------------------------- TEMPLATES -----------------------------
BASE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Online Exam System</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css" rel="stylesheet">
<style>
body{background:linear-gradient(135deg,#667eea,#764ba2,#f093fb);background-attachment:fixed;min-height:100vh}
.card{border:0;border-radius:18px;box-shadow:0 10px 30px rgba(0,0,0,.25)}
.navbar{background:rgba(0,0,0,.35)!important;backdrop-filter:blur(8px)}
.card-header{border-radius:18px 18px 0 0!important;color:#fff;font-weight:600}
.g1{background:linear-gradient(90deg,#11998e,#38ef7d)} .g2{background:linear-gradient(90deg,#f7971e,#ffd200);color:#222!important}
.g3{background:linear-gradient(90deg,#ee0979,#ff6a00)} .g4{background:linear-gradient(90deg,#2193b0,#6dd5ed)}
.btn{border-radius:30px}
.input-group .btn{border-radius:0 .375rem .375rem 0}
.opt{border:2px solid #e3e3f1;border-radius:12px;padding:10px 14px;margin:6px 0;display:block;cursor:pointer}
.opt:hover{background:#f1efff;border-color:#764ba2}
</style></head><body>
<nav class="navbar navbar-dark navbar-expand px-3 mb-4">
  <a class="navbar-brand fw-bold" href="/"><i class="bi bi-mortarboard-fill text-warning"></i> Online Exam System</a>
  <div class="ms-auto text-white">
   {% if session.get('uid') %}
     <span class="me-3"><i class="bi bi-person-circle"></i> {{ session['name'] }} ({{ session['role'] }})</span>
     <a class="btn btn-sm btn-danger" href="/logout">Logout</a>
   {% endif %}
  </div>
</nav>
<div class="container pb-5">
 {% for cat,msg in get_flashed_messages(with_categories=true) %}
   <div class="alert alert-{{ cat }} shadow">{{ msg }}</div>
 {% endfor %}
 {% block body %}{% endblock %}
</div>
<script>
document.addEventListener('click',function(e){
  var b=e.target.closest('.toggle-pw'); if(!b) return;
  var i=b.parentElement.querySelector('input'), show=(i.type==='password');
  i.type=show?'text':'password';
  b.querySelector('i').className='bi '+(show?'bi-eye-slash':'bi-eye');
});
</script></body></html>"""

LOGIN = """{% extends 'base.html' %}{% block body %}
<div class="row justify-content-center"><div class="col-md-5"><div class="card">
<div class="card-header g4 fs-5"><i class="bi bi-box-arrow-in-right"></i> Login</div>
<div class="card-body p-4"><form method="post">
 <input class="form-control mb-3" name="email" type="email" placeholder="Email" required>
 <div class="input-group mb-3">
  <input class="form-control" name="password" type="password" placeholder="Password" required>
  <button class="btn btn-outline-secondary toggle-pw" type="button" title="Show / hide password"><i class="bi bi-eye"></i></button></div>
 <button class="btn btn-primary w-100">Login</button></form>
 <p class="mt-3 mb-0 text-center">New student? <a href="/register">Register here</a></p>
<!--<p class="small text-muted text-center mb-0">Admin demo: admin@exam.com / admin123</p>-->
</div></div></div></div>{% endblock %}"""

REGISTER = """{% extends 'base.html' %}{% block body %}
<div class="row justify-content-center"><div class="col-md-5"><div class="card">
<div class="card-header g1 fs-5"><i class="bi bi-person-plus-fill"></i> Student Registration</div>
<div class="card-body p-4"><form method="post">
 <input class="form-control mb-3" name="name" placeholder="Full Name" required>
 <input class="form-control mb-3" name="email" type="email" placeholder="Email" required>
 <div class="input-group mb-3">
  <input class="form-control" name="password" type="password" placeholder="Password" minlength="4" required>
  <button class="btn btn-outline-secondary toggle-pw" type="button" title="Show / hide password"><i class="bi bi-eye"></i></button></div>
 <button class="btn btn-success w-100">Register</button></form>
 <p class="mt-3 mb-0 text-center">Already registered? <a href="/login">Login</a></p>
</div></div></div></div>{% endblock %}"""

ADMIN = """{% extends 'base.html' %}{% block body %}
<div class="row g-4">
 <div class="col-6 col-md-3"><div class="card g1 text-white text-center p-3"><h2>{{ students|length }}</h2><div><i class="bi bi-people-fill"></i> Students</div></div></div>
 <div class="col-6 col-md-3"><div class="card g3 text-white text-center p-3"><h2>{{ exams|length }}</h2><div><i class="bi bi-journal-text"></i> Exams</div></div></div>
 <div class="col-6 col-md-3"><div class="card g4 text-white text-center p-3"><h2>{{ results|length }}</h2><div><i class="bi bi-clipboard-check"></i> Attempts</div></div></div>
 <div class="col-6 col-md-3"><div class="card g2 text-center p-3"><h2>{{ exams|sum(attribute='qcount') }}</h2><div><i class="bi bi-question-circle"></i> Questions</div></div></div>
 <div class="col-md-4"><div class="card"><div class="card-header g1"><i class="bi bi-plus-circle"></i> Add New Exam</div>
  <div class="card-body"><form method="post" action="/admin/exam/add">
   <input class="form-control mb-2" name="title" placeholder="Exam title" required>
   <input class="form-control mb-2" name="duration" type="number" min="1" placeholder="Duration (minutes)" required>
   <input class="form-control mb-3" name="pass_pct" type="number" min="1" max="100" value="40" placeholder="Pass %" required>
   <button class="btn btn-success w-100">Add Exam</button></form></div></div></div>
 <div class="col-md-8"><div class="card"><div class="card-header g3"><i class="bi bi-journal-text"></i> All Exams</div>
  <div class="card-body"><table class="table align-middle">
   <tr><th>Title</th><th>Time</th><th>Pass %</th><th>Questions</th><th>Actions</th></tr>
   {% for e in exams %}<tr><td><b>{{ e.title }}</b></td><td>{{ e.duration }} min</td><td>{{ e.pass_pct }}%</td>
    <td><span class="badge bg-primary">{{ e.qcount }}</span></td>
    <td><a class="btn btn-sm btn-info" href="/admin/exam/{{ e.id }}">Questions</a>
        <a class="btn btn-sm btn-warning" href="/admin/exam/{{ e.id }}/edit">Edit</a>
        <a class="btn btn-sm btn-danger" onclick="return confirm('This will delete the exam with its questions and results. Are you sure?')" href="/admin/exam/{{ e.id }}/delete">Delete</a></td></tr>
   {% else %}<tr><td colspan="5" class="text-muted">No exams yet.</td></tr>{% endfor %}
  </table></div></div></div>
 <div class="col-12"><div class="card"><div class="card-header g1"><i class="bi bi-people-fill"></i> Registered Students</div>
  <div class="card-body"><table class="table table-hover">
   <tr><th>Name</th><th>Email</th><th>Password</th><th>Registered On</th><th>Exams Attempted</th><th>Action</th></tr>
   {% for u in students %}<tr><td><b>{{ u.name }}</b></td><td>{{ u.email }}</td>
    <td><code class="text-dark fs-6">{{ u.password_plain or '-' }}</code></td>
    <td>{{ u.registered_on or '-' }}</td><td><span class="badge bg-primary">{{ u.attempts }}</span></td>
    <td><form method="post" action="/admin/student/{{ u.id }}/delete" onsubmit="return confirm('Delete this student and all their results?')">
     <button class="btn btn-sm btn-danger"><i class="bi bi-trash"></i> Delete</button></form></td></tr>
   {% else %}<tr><td colspan="6" class="text-muted">No students registered yet.</td></tr>{% endfor %}
  </table></div></div></div>
 <div class="col-12"><div class="card"><div class="card-header g4"><i class="bi bi-bar-chart-fill"></i> All Students' Results</div>
  <div class="card-body"><table class="table table-striped">
   <tr><th>Student</th><th>Exam</th><th>Score</th><th>%</th><th>Status</th><th>Date</th><th>Action</th></tr>
   {% for r in results %}{% set p = (r.score*100/r.total)|round(1) if r.total else 0 %}
   <tr><td>{{ r.sname }}</td><td>{{ r.title }}</td><td>{{ r.score }}/{{ r.total }}</td><td>{{ p }}%</td>
    <td>{% if p >= r.pass_pct %}<span class="badge bg-success">PASS</span>{% else %}<span class="badge bg-danger">FAIL</span>{% endif %}</td>
    <td>{{ r.taken_on }}</td>
    <td><form method="post" action="/admin/result/{{ r.id }}/delete" onsubmit="return confirm('Delete this result?')">
     <button class="btn btn-sm btn-danger"><i class="bi bi-trash"></i> Delete</button></form></td></tr>
   {% else %}<tr><td colspan="7" class="text-muted">No results yet.</td></tr>{% endfor %}
  </table></div></div></div>
</div>{% endblock %}"""

EXAM_EDIT = """{% extends 'base.html' %}{% block body %}
<div class="row justify-content-center"><div class="col-md-5"><div class="card">
<div class="card-header g2"><i class="bi bi-pencil-square"></i> Edit Exam</div>
<div class="card-body"><form method="post">
 <label class="form-label">Title</label><input class="form-control mb-2" name="title" value="{{ e.title }}" required>
 <label class="form-label">Duration (min)</label><input class="form-control mb-2" name="duration" type="number" value="{{ e.duration }}" required>
 <label class="form-label">Pass %</label><input class="form-control mb-3" name="pass_pct" type="number" value="{{ e.pass_pct }}" required>
 <button class="btn btn-warning">Update</button> <a class="btn btn-secondary" href="/admin">Cancel</a></form></div></div></div></div>{% endblock %}"""

QUESTIONS = """{% extends 'base.html' %}{% block body %}
<div class="row g-4">
 <div class="col-md-5"><div class="card"><div class="card-header g1"><i class="bi bi-plus-circle"></i> Add Question — {{ e.title }}</div>
  <div class="card-body">{% set x = None %}{% include 'qform.html' %}</div></div></div>
 <div class="col-md-7"><div class="card"><div class="card-header g3"><i class="bi bi-list-check"></i> Questions ({{ qs|length }})</div>
  <div class="card-body">
  {% for x in qs %}<div class="border rounded-3 p-3 mb-3">
    <b>Q{{ loop.index }}. {{ x.text }}</b>
    <div class="small mt-1">A) {{ x.a }} &nbsp; B) {{ x.b }} &nbsp; C) {{ x.c }} &nbsp; D) {{ x.d }}</div>
    <span class="badge bg-success mt-1">Correct: {{ x.correct }}</span>
    <div class="mt-2"><a class="btn btn-sm btn-warning" href="/admin/q/{{ x.id }}/edit">Edit</a>
    <a class="btn btn-sm btn-danger" onclick="return confirm('Delete question?')" href="/admin/q/{{ x.id }}/delete">Delete</a></div></div>
  {% else %}<p class="text-muted">No questions yet.</p>{% endfor %}
  <a class="btn btn-secondary" href="/admin">&larr; Back</a></div></div></div></div>{% endblock %}"""

QFORM = """<form method="post" action="{{ '/admin/q/%d/edit' % x.id if x else '/admin/exam/%d/q/add' % e.id }}">
 <textarea class="form-control mb-2" name="text" placeholder="Question" required>{{ x.text if x else '' }}</textarea>
 {% for k in ['a','b','c','d'] %}<input class="form-control mb-2" name="{{ k }}" placeholder="Option {{ k.upper() }}" value="{{ x[k] if x else '' }}" required>{% endfor %}
 <select class="form-select mb-3" name="correct" required>
  {% for k in ['A','B','C','D'] %}<option value="{{ k }}" {{ 'selected' if x and x.correct==k }}>Correct answer: {{ k }}</option>{% endfor %}
 </select><button class="btn btn-success w-100">{{ 'Update' if x else 'Add Question' }}</button></form>"""

QEDIT = """{% extends 'base.html' %}{% block body %}
<div class="row justify-content-center"><div class="col-md-6"><div class="card">
<div class="card-header g2"><i class="bi bi-pencil-square"></i> Edit Question</div>
<div class="card-body">{% include 'qform.html' %}<a class="btn btn-secondary mt-2" href="/admin/exam/{{ x.exam_id }}">Cancel</a></div></div></div></div>{% endblock %}"""

STUDENT = """{% extends 'base.html' %}{% block body %}
<div class="row g-4">
 <div class="col-md-6"><div class="card"><div class="card-header g1"><i class="bi bi-pencil-fill"></i> Available Exams</div>
  <div class="card-body">
  {% for e in exams %}<div class="d-flex justify-content-between align-items-center border rounded-3 p-3 mb-2">
   <div><b>{{ e.title }}</b><br><small class="text-muted">{{ e.qcount }} questions • {{ e.duration }} min • Pass {{ e.pass_pct }}%</small></div>
   {% if e.qcount %}<a class="btn btn-primary" href="/exam/{{ e.id }}">Start <i class="bi bi-play-fill"></i></a>{% endif %}</div>
  {% else %}<p class="text-muted">No exams available.</p>{% endfor %}</div></div></div>
 <div class="col-md-6"><div class="card"><div class="card-header g3"><i class="bi bi-trophy-fill"></i> My Results</div>
  <div class="card-body"><table class="table">
   <tr><th>Exam</th><th>Score</th><th>Status</th><th>Date</th></tr>
   {% for r in results %}{% set p = (r.score*100/r.total)|round(1) if r.total else 0 %}
   <tr><td><a href="/result/{{ r.id }}">{{ r.title }}</a></td><td>{{ r.score }}/{{ r.total }} ({{ p }}%)</td>
   <td>{% if p >= r.pass_pct %}<span class="badge bg-success">PASS</span>{% else %}<span class="badge bg-danger">FAIL</span>{% endif %}</td>
   <td class="small">{{ r.taken_on }}</td></tr>
   {% else %}<tr><td colspan="4" class="text-muted">You have not taken any exam yet.</td></tr>{% endfor %}
  </table></div></div></div></div>{% endblock %}"""

ATTEMPT = """{% extends 'base.html' %}{% block body %}
<div class="card"><div class="card-header g4 d-flex justify-content-between">
 <span><i class="bi bi-pencil-square"></i> {{ e.title }}</span>
 <span class="badge bg-dark fs-6"><i class="bi bi-stopwatch"></i> <span id="t">--:--</span></span></div>
<div class="card-body"><form method="post" action="/exam/{{ e.id }}/submit" id="f">
 {% for x in qs %}<div class="mb-4"><h6><b>Q{{ loop.index }}.</b> {{ x.text }}</h6>
  {% for k in ['a','b','c','d'] %}<label class="opt"><input type="radio" name="q{{ x.id }}" value="{{ k.upper() }}"> <b>{{ k.upper() }}.</b> {{ x[k] }}</label>{% endfor %}</div>{% endfor %}
 <button class="btn btn-success btn-lg">Submit Exam</button></form></div></div>
<script>
let s={{ e.duration*60 }};const t=document.getElementById('t');
const iv=setInterval(()=>{let m=Math.floor(s/60),c=s%60;t.textContent=String(m).padStart(2,'0')+':'+String(c).padStart(2,'0');
 if(s--<=0){clearInterval(iv);document.getElementById('f').submit();}},1000);
</script>{% endblock %}"""

RESULT = """{% extends 'base.html' %}{% block body %}
<div class="row justify-content-center"><div class="col-md-6"><div class="card text-center">
<div class="card-header {{ 'g1' if passed else 'g3' }} fs-4">{{ 'Congratulations! PASS 🎉' if passed else 'Better luck next time ❌' }}</div>
<div class="card-body p-4"><h5>{{ r.title }}</h5>
 <h1 class="display-3 fw-bold">{{ r.score }} / {{ r.total }}</h1>
 <div class="progress my-3" style="height:25px"><div class="progress-bar {{ 'bg-success' if passed else 'bg-danger' }}" style="width:{{ pct }}%">{{ pct }}%</div></div>
 <p class="text-muted">Required to pass: {{ r.pass_pct }}% • {{ r.taken_on }}</p>
 <a class="btn btn-primary" href="/student">Dashboard</a></div></div></div></div>{% endblock %}"""

# ------------------------------- APP ---------------------------------
app = Flask(__name__)
app.secret_key = "colab-exam-secret"
app.jinja_loader = DictLoader({
    "base.html": BASE, "login.html": LOGIN, "register.html": REGISTER, "admin.html": ADMIN,
    "exam_edit.html": EXAM_EDIT, "questions.html": QUESTIONS, "qform.html": QFORM, "qedit.html": QEDIT,
    "student.html": STUDENT, "attempt.html": ATTEMPT, "result.html": RESULT})

def need(role):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if session.get("uid") and not q("SELECT 1 FROM users WHERE id=?", (session["uid"],), one=True):
                session.clear()                  # account was deleted by admin
            if session.get("role") != role:
                flash("Please login first.", "warning")
                return redirect("/login")
            return f(*a, **k)
        return w
    return deco

@app.route("/")
def home():
    if session.get("role") == "admin": return redirect("/admin")
    if session.get("role") == "student": return redirect("/student")
    return redirect("/login")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        if q("SELECT 1 FROM users WHERE email=?", (f["email"].lower(),), one=True):
            flash("This email is already registered.", "danger")
        else:
            q("INSERT INTO users(name,email,password,role,registered_on,password_plain) VALUES(?,?,?,'student',?,?)",
              (f["name"], f["email"].lower(), generate_password_hash(f["password"]),
               datetime.now().strftime("%d-%m-%Y %H:%M"), f["password"]), commit=True)
            flash("Registration successful! Please login.", "success")
            return redirect("/login")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = q("SELECT * FROM users WHERE email=?", (request.form["email"].lower(),), one=True)
        if u and check_password_hash(u["password"], request.form["password"]):
            session.update(uid=u["id"], name=u["name"], role=u["role"])
            return redirect("/")
        flash("Wrong email or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# -------- Admin: exams --------
@app.route("/admin")
@need("admin")
def admin():
    exams = q("SELECT e.*, (SELECT COUNT(*) FROM questions WHERE exam_id=e.id) qcount FROM exams e")
    results = q("""SELECT r.*, u.name sname, e.title, e.pass_pct FROM results r
                   JOIN users u ON u.id=r.user_id JOIN exams e ON e.id=r.exam_id ORDER BY r.id DESC""")
    students = q("""SELECT u.*, (SELECT COUNT(*) FROM results WHERE user_id=u.id) attempts
                    FROM users u WHERE u.role='student' ORDER BY u.id DESC""")
    return render_template("admin.html", exams=exams, results=results, students=students)

@app.route("/admin/exam/add", methods=["POST"])
@need("admin")
def exam_add():
    f = request.form
    q("INSERT INTO exams(title,duration,pass_pct) VALUES(?,?,?)", (f["title"], f["duration"], f["pass_pct"]), commit=True)
    flash("Exam added.", "success")
    return redirect("/admin")

@app.route("/admin/exam/<int:i>/edit", methods=["GET", "POST"])
@need("admin")
def exam_edit(i):
    if request.method == "POST":
        f = request.form
        q("UPDATE exams SET title=?,duration=?,pass_pct=? WHERE id=?", (f["title"], f["duration"], f["pass_pct"], i), commit=True)
        flash("Exam updated.", "success")
        return redirect("/admin")
    return render_template("exam_edit.html", e=q("SELECT * FROM exams WHERE id=?", (i,), one=True))

@app.route("/admin/exam/<int:i>/delete")
@need("admin")
def exam_delete(i):
    q("DELETE FROM questions WHERE exam_id=?", (i,), commit=True)
    q("DELETE FROM results WHERE exam_id=?", (i,), commit=True)
    q("DELETE FROM exams WHERE id=?", (i,), commit=True)
    flash("Exam deleted.", "warning")
    return redirect("/admin")

@app.route("/admin/student/<int:i>/delete", methods=["POST"])
@need("admin")
def student_delete(i):
    if q("SELECT 1 FROM users WHERE id=? AND role='student'", (i,), one=True):
        q("DELETE FROM results WHERE user_id=?", (i,), commit=True)
        q("DELETE FROM users WHERE id=?", (i,), commit=True)
        flash("Student deleted.", "warning")
    return redirect("/admin")

@app.route("/admin/result/<int:i>/delete", methods=["POST"])
@need("admin")
def result_delete(i):
    q("DELETE FROM results WHERE id=?", (i,), commit=True)
    flash("Result deleted.", "warning")
    return redirect("/admin")

# -------- Admin: questions --------
@app.route("/admin/exam/<int:i>")
@need("admin")
def questions(i):
    return render_template("questions.html", e=q("SELECT * FROM exams WHERE id=?", (i,), one=True),
                           qs=q("SELECT * FROM questions WHERE exam_id=?", (i,)))

@app.route("/admin/exam/<int:i>/q/add", methods=["POST"])
@need("admin")
def q_add(i):
    f = request.form
    q("INSERT INTO questions(exam_id,text,a,b,c,d,correct) VALUES(?,?,?,?,?,?,?)",
      (i, f["text"], f["a"], f["b"], f["c"], f["d"], f["correct"]), commit=True)
    flash("Question added.", "success")
    return redirect(f"/admin/exam/{i}")

@app.route("/admin/q/<int:i>/edit", methods=["GET", "POST"])
@need("admin")
def q_edit(i):
    x = q("SELECT * FROM questions WHERE id=?", (i,), one=True)
    if request.method == "POST":
        f = request.form
        q("UPDATE questions SET text=?,a=?,b=?,c=?,d=?,correct=? WHERE id=?",
          (f["text"], f["a"], f["b"], f["c"], f["d"], f["correct"], i), commit=True)
        flash("Question updated.", "success")
        return redirect(f"/admin/exam/{x['exam_id']}")
    return render_template("qedit.html", x=x)

@app.route("/admin/q/<int:i>/delete")
@need("admin")
def q_delete(i):
    x = q("SELECT * FROM questions WHERE id=?", (i,), one=True)
    q("DELETE FROM questions WHERE id=?", (i,), commit=True)
    flash("Question deleted.", "warning")
    return redirect(f"/admin/exam/{x['exam_id']}")

# -------- Student --------
@app.route("/student")
@need("student")
def student():
    exams = q("SELECT e.*, (SELECT COUNT(*) FROM questions WHERE exam_id=e.id) qcount FROM exams e")
    results = q("""SELECT r.*, e.title, e.pass_pct FROM results r JOIN exams e ON e.id=r.exam_id
                   WHERE r.user_id=? ORDER BY r.id DESC""", (session["uid"],))
    return render_template("student.html", exams=exams, results=results)

@app.route("/exam/<int:i>")
@need("student")
def attempt(i):
    return render_template("attempt.html", e=q("SELECT * FROM exams WHERE id=?", (i,), one=True),
                           qs=q("SELECT * FROM questions WHERE exam_id=?", (i,)))

@app.route("/exam/<int:i>/submit", methods=["POST"])
@need("student")
def submit(i):
    qs = q("SELECT * FROM questions WHERE exam_id=?", (i,))
    score = sum(1 for x in qs if request.form.get(f"q{x['id']}") == x["correct"])   # auto marks
    rid = q("INSERT INTO results(user_id,exam_id,score,total,taken_on) VALUES(?,?,?,?,?)",
            (session["uid"], i, score, len(qs), datetime.now().strftime("%d-%m-%Y %H:%M")), commit=True)
    return redirect(f"/result/{rid}")

@app.route("/result/<int:i>")
@need("student")
def result(i):
    r = q("SELECT r.*, e.title, e.pass_pct FROM results r JOIN exams e ON e.id=r.exam_id WHERE r.id=? AND r.user_id=?",
          (i, session["uid"]), one=True)
    pct = round(r["score"] * 100 / r["total"], 1) if r["total"] else 0
    return render_template("result.html", r=r, pct=pct, passed=pct >= r["pass_pct"])

init_db()

# 2 page
import threading
from google.colab import output

threading.Thread(target=lambda: app.run(port=5000, use_reloader=False), daemon=True).start()
output.serve_kernel_port_as_window(5000)