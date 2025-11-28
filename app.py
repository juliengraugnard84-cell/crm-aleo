###############################################
#        Mini CRM + Chat d'équipe simple      #
###############################################

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, send_file, send_from_directory, jsonify
)
from flask_sqlalchemy import SQLAlchemy
from functools import wraps
import os
from datetime import datetime, date
from io import BytesIO

from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import inspect, text

# ——————————————————————————————
# AUCUNE IA — AUCUN CHARGEMENT .env
# ——————————————————————————————

app = Flask(__name__)
app.secret_key = "dev-secret"

# ============================================================
#                    CONFIG BASE DE DONNÉES
# ============================================================

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///crm.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

UPLOAD_FOLDER = os.path.join(app.root_path, "uploads")
CHAT_UPLOAD_FOLDER = os.path.join(app.root_path, "chat_uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CHAT_UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["CHAT_UPLOAD_FOLDER"] = CHAT_UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {"pdf"}

db = SQLAlchemy(app)

CLIENT_STATUSES = [
    "en cours",
    "demande de cotation",
    "rdv fixé",
    "contrat signé",
    "refusé",
    "en attente de retour client",
]

# ============================================================
#                       HELPERS / DÉCORATEURS
# ============================================================

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Veuillez vous connecter.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Accès réservé à l’administrateur.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper

# ============================================================
#                           MODÈLES
# ============================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="commercial")

    clients = db.relationship("Client", backref="user", lazy=True)
    appointments = db.relationship("Appointment", backref="user", lazy=True)
    documents = db.relationship("Document", backref="user", lazy=True)
    messages = db.relationship("Message", backref="user", lazy=True)

    def set_password(self, pwd: str):
        self.password_hash = generate_password_hash(pwd)

    def check_password(self, pwd: str) -> bool:
        return check_password_hash(self.password_hash, pwd)


class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(50))
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)

    commercial = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(50), nullable=False, default="en cours")

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    appointments = db.relationship("Appointment", backref="client", lazy=True)
    documents = db.relationship("Document", backref="client", lazy=True)


class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    client_name = db.Column(db.String(120), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    notes = db.Column(db.Text)

    client_id = db.Column(db.Integer, db.ForeignKey("client.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    client_id = db.Column(db.Integer, db.ForeignKey("client.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class Revenue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    commercial = db.Column(db.String(120), nullable=False)
    montant = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False, default="")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    filename = db.Column(db.String(255))
    original_name = db.Column(db.String(255))
# ============================================================
#                           LOGIN / LOGOUT
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session["user_id"] = user.id
            session["username"] = user.username
            session["role"] = user.role
            flash("Connexion réussie", "success")
            return redirect(url_for("dashboard"))

        flash("Nom d’utilisateur ou mot de passe incorrect", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Déconnexion réussie", "info")
    return redirect(url_for("login"))


# ============================================================
#              ADMIN : GESTION DES UTILISATEURS
# ============================================================

@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Nom d’utilisateur et mot de passe requis.", "error")
            return redirect(url_for("admin_users"))

        if User.query.filter_by(username=username).first():
            flash("Ce nom d’utilisateur existe déjà", "error")
            return redirect(url_for("admin_users"))

        new_user = User(username=username, role="commercial")
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        flash("Commercial créé", "success")
        return redirect(url_for("admin_users"))

    users = User.query.all()
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.role == "admin":
        flash("Impossible de modifier l'administrateur principal.", "error")
        return redirect(url_for("admin_users"))

    if request.method == "POST":
        user.username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if password.strip():
            user.set_password(password)

        db.session.commit()
        flash("Utilisateur modifié", "success")
        return redirect(url_for("admin_users"))

    return render_template("admin_edit_user.html", user=user)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.role == "admin":
        flash("Impossible de supprimer l’admin.", "error")
        return redirect(url_for("admin_users"))

    admin_user = User.query.filter_by(role="admin").first()

    # Réassignation automatique
    for c in Client.query.filter_by(user_id=user.id).all():
        c.user_id = admin_user.id
    for r in Appointment.query.filter_by(user_id=user.id).all():
        r.user_id = admin_user.id
    for d in Document.query.filter_by(user_id=user.id).all():
        d.user_id = admin_user.id
    for m in Message.query.filter_by(user_id=user.id).all():
        m.user_id = admin_user.id

    db.session.delete(user)
    db.session.commit()

    flash("Utilisateur supprimé", "info")
    return redirect(url_for("admin_users"))


# ============================================================
#                           DASHBOARD
# ============================================================

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    role = session["role"]

    if role == "admin":
        clients_count = Client.query.count()
        docs_count = Document.query.count()
        rdv_count = Appointment.query.count()
        upcoming = Appointment.query.order_by(
            Appointment.date.asc(), Appointment.time.asc()
        ).limit(5).all()
        latest_docs = Document.query.order_by(
            Document.uploaded_at.desc()
        ).limit(5).all()
    else:
        clients_count = Client.query.filter_by(user_id=user_id).count()
        docs_count = Document.query.filter_by(user_id=user_id).count()
        rdv_count = Appointment.query.filter_by(user_id=user_id).count()
        upcoming = Appointment.query.filter_by(user_id=user_id).order_by(
            Appointment.date.asc(), Appointment.time.asc()
        ).limit(5).all()
        latest_docs = Document.query.filter_by(user_id=user_id).order_by(
            Document.uploaded_at.desc()
        ).limit(5).all()

    stats = {
        "clients_total": clients_count,
        "documents_partages": docs_count,
        "opportunites_ouvertes": rdv_count,
        "rdv_cette_semaine": rdv_count,
    }

    return render_template(
        "dashboard.html",
        stats=stats,
        upcoming_appointments=upcoming,
        latest_docs=latest_docs,
    )


# ============================================================
#                           CLIENTS
# ============================================================

@app.route("/clients")
@login_required
def clients():
    q = request.args.get("q", "")
    role = session["role"]
    user_id = session["user_id"]

    base = Client.query if role == "admin" else Client.query.filter_by(user_id=user_id)

    if q:
        like = f"%{q}%"
        base = base.filter(
            (Client.name.ilike(like))
            | (Client.email.ilike(like))
            | (Client.phone.ilike(like))
            | (Client.commercial.ilike(like))
            | (Client.status.ilike(like))
        )

    all_clients = base.order_by(Client.name.asc()).all()
    return render_template("clients.html", clients=all_clients, q=q)


@app.route("/clients/new", methods=["GET", "POST"])
@login_required
def new_client():
    if request.method == "POST":
        client = Client(
            name=request.form.get("name"),
            email=request.form.get("email"),
            phone=request.form.get("phone"),
            address=request.form.get("address"),
            notes=request.form.get("notes"),
            commercial=request.form.get("commercial"),
            status=request.form.get("status") or "en cours",
            user_id=session["user_id"],
        )

        db.session.add(client)
        db.session.commit()

        flash("Client ajouté", "success")
        return redirect(url_for("clients"))

    return render_template(
        "client_form.html",
        client=None,
        action="new",
        statuses=CLIENT_STATUSES,
    )
# ============================================================
#                         RENDEZ-VOUS
# ============================================================

@app.route("/appointments")
@login_required
def list_appointments():
    user_id = session["user_id"]
    role = session["role"]
    date_str = request.args.get("date")

    base = Appointment.query if role == "admin" else Appointment.query.filter_by(user_id=user_id)

    if date_str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            appointments = base.filter_by(date=d).order_by(Appointment.time.asc()).all()
        except:
            appointments = base.order_by(Appointment.date.asc(), Appointment.time.asc()).all()
    else:
        appointments = base.order_by(Appointment.date.asc(), Appointment.time.asc()).all()

    return render_template("appointments.html", appointments=appointments)


@app.route("/appointments/new", methods=["GET", "POST"])
@login_required
def new_appointment():
    client_id = request.args.get("client_id")
    client = Client.query.get(client_id) if client_id else None

    if request.method == "POST":
        date_val = datetime.strptime(request.form.get("date"), "%Y-%m-%d").date()
        time_val = datetime.strptime(request.form.get("time"), "%H:%M").time()

        rdv = Appointment(
            title=request.form.get("title"),
            notes=request.form.get("notes"),
            date=date_val,
            time=time_val,
            client_id=client.id if client else None,
            client_name=client.name if client else request.form.get("client_name"),
            user_id=session["user_id"],
        )

        db.session.add(rdv)
        db.session.commit()

        flash("RDV ajouté", "success")

        if client:
            return redirect(url_for("client_detail", client_id=client.id))
        return redirect(url_for("list_appointments"))

    return render_template("appointment_form.html", rdv=None, client=client, action="new")


@app.route("/appointments/<int:appointment_id>/edit", methods=["GET", "POST"])
@login_required
def edit_appointment(appointment_id):
    rdv = Appointment.query.get_or_404(appointment_id)
    client = rdv.client

    if session["role"] != "admin" and rdv.user_id != session["user_id"]:
        flash("Accès interdit", "error")
        return redirect(url_for("list_appointments"))

    if request.method == "POST":
        rdv.title = request.form.get("title")
        rdv.notes = request.form.get("notes")
        rdv.date = datetime.strptime(request.form.get("date"), "%Y-%m-%d").date()
        rdv.time = datetime.strptime(request.form.get("time"), "%H:%M").time()
        rdv.client_name = client.name if client else request.form.get("client_name")

        db.session.commit()
        flash("RDV modifié", "success")

        if client:
            return redirect(url_for("client_detail", client_id=client.id))
        return redirect(url_for("list_appointments"))

    return render_template("appointment_form.html", rdv=rdv, client=client, action="edit")


@app.route("/appointments/<int:appointment_id>/delete", methods=["POST"])
@login_required
def delete_appointment(appointment_id):
    rdv = Appointment.query.get_or_404(appointment_id)

    if session["role"] != "admin" and rdv.user_id != session["user_id"]:
        flash("Accès interdit", "error")
        return redirect(url_for("list_appointments"))

    client = rdv.client
    db.session.delete(rdv)
    db.session.commit()

    flash("RDV supprimé", "info")

    if client:
        return redirect(url_for("client_detail", client_id=client.id))
    return redirect(url_for("list_appointments"))


# ============================================================
#                        DOCUMENTS PDF
# ============================================================

@app.route("/documents")
@login_required
def documents():
    role = session["role"]
    user_id = session["user_id"]

    docs = Document.query.order_by(Document.uploaded_at.desc()).all() if role == "admin" \
           else Document.query.filter_by(user_id=user_id).order_by(Document.uploaded_at.desc()).all()

    return render_template("documents.html", documents=docs)


@app.route("/documents/upload", methods=["POST"])
@login_required
def upload_document():
    file = request.files.get("file")
    user_id = session["user_id"]

    client_id = request.form.get("client_id")
    client = Client.query.get(client_id) if client_id else None

    if not file or file.filename == "":
        flash("Aucun fichier envoyé", "error")
        return redirect(request.referrer or url_for("documents"))

    if not allowed_file(file.filename):
        flash("Seuls les fichiers PDF sont autorisés.", "error")
        return redirect(request.referrer or url_for("documents"))

    original = file.filename
    safe_name = f"{int(datetime.utcnow().timestamp())}_{original}"

    file.save(os.path.join(app.config["UPLOAD_FOLDER"], safe_name))

    doc = Document(
        filename=safe_name,
        original_name=original,
        client_id=client.id if client else None,
        user_id=user_id,
    )

    db.session.add(doc)
    db.session.commit()

    flash("PDF importé", "success")
    return redirect(request.referrer or url_for("documents"))


@app.route("/documents/<int:doc_id>/download")
@login_required
def download_document(doc_id):
    doc = Document.query.get_or_404(doc_id)

    if session["role"] != "admin" and doc.user_id != session["user_id"]:
        flash("Accès interdit", "error")
        return redirect(url_for("documents"))

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        doc.filename,
        as_attachment=True,
        download_name=doc.original_name,
    )


@app.route("/documents/<int:doc_id>/delete", methods=["POST"])
@login_required
def delete_document(doc_id):
    doc = Document.query.get_or_404(doc_id)

    if session["role"] != "admin" and doc.user_id != session["user_id"]:
        flash("Accès interdit", "error")
        return redirect(url_for("documents"))

    path = os.path.join(app.config["UPLOAD_FOLDER"], doc.filename)
    if os.path.exists(path):
        os.remove(path)

    db.session.delete(doc)
    db.session.commit()

    flash("Document supprimé", "info")
    return redirect(url_for("documents"))


# ============================================================
#                       CHIFFRE D’AFFAIRES
# ============================================================

@app.route("/chiffre_affaire", methods=["GET", "POST"])
@login_required
def chiffre_affaire():
    if request.method == "POST":
        try:
            montant = float(request.form.get("montant"))
            date_val = datetime.strptime(request.form.get("date"), "%Y-%m-%d").date()
        except:
            flash("Montant ou date invalide.", "error")
            return redirect(url_for("chiffre_affaire"))

        entry = Revenue(
            commercial=session["username"],
            montant=montant,
            date=date_val,
        )

        db.session.add(entry)
        db.session.commit()

        flash("Montant ajouté", "success")
        return redirect(url_for("chiffre_affaire"))

    if session["role"] == "admin":
        entries = Revenue.query.order_by(Revenue.date.desc()).all()
    else:
        entries = Revenue.query.filter_by(commercial=session["username"]) \
                               .order_by(Revenue.date.desc()).all()

    total = sum(e.montant for e in entries)

    return render_template(
        "chiffre_affaire.html",
        entries=entries,
        total=total,
    )
# ============================================================
#                          CHAT D'ÉQUIPE
# ============================================================

@app.route("/chat")
@login_required
def chat():
    msgs = Message.query.order_by(Message.timestamp.asc()).all()
    return render_template("chat.html", messages=msgs)


@app.route("/chat/send", methods=["POST"])
@login_required
def chat_send():
    content = (request.form.get("message") or "").strip()
    file = request.files.get("file")

    filename = None
    original_name = None

    # Gestion du fichier uploadé
    if file and file.filename:
        original_name = file.filename
        safe_name = f"{int(datetime.utcnow().timestamp())}_{original_name}"
        file.save(os.path.join(app.config["CHAT_UPLOAD_FOLDER"], safe_name))
        filename = safe_name

    # Si message vide ET aucun fichier -> erreur
    if not content and not filename:
        flash("Message vide : écrivez un texte ou joignez un fichier.", "error")
        return redirect(url_for("chat"))

    msg = Message(
        user_id=session["user_id"],
        content=content or "",
        filename=filename,
        original_name=original_name,
    )

    db.session.add(msg)
    db.session.commit()

    return redirect(url_for("chat"))


@app.route("/chat/file/<int:msg_id>")
@login_required
def chat_download(msg_id):
    msg = Message.query.get_or_404(msg_id)

    if not msg.filename:
        flash("Aucun fichier joint.", "error")
        return redirect(url_for("chat"))

    return send_from_directory(
        app.config["CHAT_UPLOAD_FOLDER"],
        msg.filename,
        as_attachment=True,
        download_name=msg.original_name or msg.filename,
    )


# ============================================================
#                 INITIALISATION DB + ADMIN AUTO
# ============================================================

with app.app_context():
    db.create_all()

    inspector = inspect(db.engine)

    # Ajout automatique des colonnes manquantes
    cols = [c["name"] for c in inspector.get_columns("client")]
    if "status" not in cols:
        with db.engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE client "
                "ADD COLUMN status VARCHAR(50) NOT NULL DEFAULT 'en cours'"
            ))

    msg_cols = [c["name"] for c in inspector.get_columns("message")]
    if "filename" not in msg_cols:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE message ADD COLUMN filename VARCHAR(255)"))

    msg_cols = [c["name"] for c in inspector.get_columns("message")]
    if "original_name" not in msg_cols:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE message ADD COLUMN original_name VARCHAR(255)"))

    # Création auto de l'admin si aucun admin trouvé
    if not User.query.filter_by(role="admin").first():
        admin = User(username="admin", role="admin")
        admin.set_password("admin123")
        db.session.add(admin)
        db.session.commit()
        print(">>> ADMIN CRÉÉ (admin / admin123)")


# ============================================================
#                          LANCEMENT
# ============================================================

if __name__ == "__main__":
    app.run(debug=True)
