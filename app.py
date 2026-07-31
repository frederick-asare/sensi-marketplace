import os
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "marketplace.db")
)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB max upload

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default="farmer")  # farmer, buyer, or admin

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Listing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    crop_type = db.Column(db.String(80))
    quantity = db.Column(db.String(80))  # e.g. "50 kg", "20 bags"
    location = db.Column(db.String(120))
    price = db.Column(db.Float, nullable=False)
    image_filename = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    farmer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    farmer = db.relationship("User", backref="listings")


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listing.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    message = db.Column(db.Text)
    status = db.Column(db.String(20), default="pending")  # pending, accepted, declined
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    listing = db.relationship("Listing", backref="orders")
    buyer = db.relationship("User", backref="orders")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)
    return wrapper


@app.route("/")
def index():
    query = Listing.query

    crop_type = request.args.get("crop_type", "").strip()
    location = request.args.get("location", "").strip()
    max_price = request.args.get("max_price", "").strip()

    if crop_type:
        query = query.filter(Listing.crop_type.ilike(f"%{crop_type}%"))
    if location:
        query = query.filter(Listing.location.ilike(f"%{location}%"))
    if max_price:
        try:
            query = query.filter(Listing.price <= float(max_price))
        except ValueError:
            flash("Max price must be a number.")

    listings = query.order_by(Listing.created_at.desc()).all()
    return render_template(
        "index.html",
        listings=listings,
        crop_type=crop_type,
        location=location,
        max_price=max_price,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "farmer")
        if role not in ("farmer", "buyer"):
            role = "farmer"  # admin accounts are never created via the public form

        if not username or not password:
            flash("Username and password are required.")
            return redirect(url_for("register"))

        if User.query.filter_by(username=username).first():
            flash("That username is already taken.")
            return redirect(url_for("register"))

        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Account created — please log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash("Logged in successfully.")
            return redirect(url_for("index"))

        flash("Invalid username or password.")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.")
    return redirect(url_for("index"))


@app.route("/listings/new", methods=["GET", "POST"])
@login_required
def new_listing():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        crop_type = request.form.get("crop_type", "").strip()
        quantity = request.form.get("quantity", "").strip()
        location = request.form.get("location", "").strip()
        price = request.form.get("price", "0")
        file = request.files.get("image")

        if not title or not price:
            flash("Title and price are required.")
            return redirect(url_for("new_listing"))

        try:
            price_value = float(price)
        except ValueError:
            flash("Price must be a number.")
            return redirect(url_for("new_listing"))

        image_filename = None
        if file and file.filename:
            if not allowed_file(file.filename):
                flash("Only image files (png, jpg, jpeg, gif) are allowed.")
                return redirect(url_for("new_listing"))
            filename = secure_filename(file.filename)
            unique_name = f"{current_user.id}_{int(datetime.utcnow().timestamp())}_{filename}"
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], unique_name))
            image_filename = unique_name

        listing = Listing(
            title=title,
            description=description,
            crop_type=crop_type,
            quantity=quantity,
            location=location,
            price=price_value,
            image_filename=image_filename,
            farmer_id=current_user.id,
        )
        db.session.add(listing)
        db.session.commit()
        flash("Listing created.")
        return redirect(url_for("index"))

    return render_template("new_listing.html")


@app.route("/listings/<int:listing_id>/interested", methods=["POST"])
@login_required
def express_interest(listing_id):
    listing = Listing.query.get_or_404(listing_id)

    if listing.farmer_id == current_user.id:
        flash("You can't place an order on your own listing.")
        return redirect(url_for("index"))

    message = request.form.get("message", "").strip()
    order = Order(listing_id=listing.id, buyer_id=current_user.id, message=message)
    db.session.add(order)
    db.session.commit()
    flash(f"Interest sent to {listing.farmer.username} for '{listing.title}'.")
    return redirect(url_for("my_orders"))


@app.route("/my-orders")
@login_required
def my_orders():
    if current_user.role == "farmer":
        # orders placed on this farmer's listings
        orders = (
            Order.query.join(Listing)
            .filter(Listing.farmer_id == current_user.id)
            .order_by(Order.created_at.desc())
            .all()
        )
    else:
        # orders this buyer has placed
        orders = (
            Order.query.filter_by(buyer_id=current_user.id)
            .order_by(Order.created_at.desc())
            .all()
        )
    return render_template("my_orders.html", orders=orders)


@app.route("/orders/<int:order_id>/status", methods=["POST"])
@login_required
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    if order.listing.farmer_id != current_user.id:
        abort(403)

    new_status = request.form.get("status")
    if new_status in ("accepted", "declined"):
        order.status = new_status
        db.session.commit()
        flash("Order updated.")
    return redirect(url_for("my_orders"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ---------------- Admin ----------------

@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    user_count = User.query.count()
    listing_count = Listing.query.count()
    order_count = Order.query.count()
    return render_template(
        "admin_dashboard.html",
        user_count=user_count,
        listing_count=listing_count,
        order_count=order_count,
    )


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.id).all()
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    if user_id == current_user.id:
        flash("You can't delete your own admin account.")
        return redirect(url_for("admin_users"))

    user = User.query.get_or_404(user_id)
    Listing.query.filter_by(farmer_id=user.id).delete()
    Order.query.filter_by(buyer_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash(f"User '{user.username}' deleted.")
    return redirect(url_for("admin_users"))


@app.route("/admin/listings")
@login_required
@admin_required
def admin_listings():
    listings = Listing.query.order_by(Listing.created_at.desc()).all()
    return render_template("admin_listings.html", listings=listings)


@app.route("/admin/listings/<int:listing_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    Order.query.filter_by(listing_id=listing.id).delete()
    db.session.delete(listing)
    db.session.commit()
    flash(f"Listing '{listing.title}' removed.")
    return redirect(url_for("admin_listings"))


@app.route("/admin/logs")
@login_required
@admin_required
def admin_logs():
    # Simple activity log view built from existing records — good enough for
    # a coursework demo; a real deployment would use structured app logging.
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(50).all()
    recent_listings = Listing.query.order_by(Listing.created_at.desc()).limit(50).all()
    return render_template(
        "admin_logs.html", recent_orders=recent_orders, recent_listings=recent_listings
    )


@app.route("/healthz")
def healthz():
    return {"status": "ok"}


def init_db():
    with app.app_context():
        db.create_all()


# Ensure tables exist whether run via `python app.py` or via gunicorn
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=False)
