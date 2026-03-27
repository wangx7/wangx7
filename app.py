import sqlite3
import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, g, abort, session

app = Flask(__name__)
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    logging.warning(
        "SECRET_KEY env var is not set. Using an insecure default key. "
        "Set SECRET_KEY in production."
    )
    _secret = "dev-secret-change-in-prod"
app.secret_key = _secret

# Admin password for protected operations (delete). Set ADMIN_PASSWORD env var.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

DATABASE = os.path.join(os.path.dirname(__file__), "blog.db")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            title     TEXT NOT NULL,
            content   TEXT NOT NULL,
            author    TEXT NOT NULL DEFAULT '博主',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS posts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            title     TEXT NOT NULL,
            content   TEXT NOT NULL,
            author    TEXT NOT NULL DEFAULT '匿名用户',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS comments (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id   INTEGER NOT NULL REFERENCES posts(id),
            content   TEXT NOT NULL,
            author    TEXT NOT NULL DEFAULT '匿名用户',
            created_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    db.close()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_admin():
    """Return True if the current session is authenticated as admin."""
    return session.get("is_admin") is True


def admin_required(f):
    """Decorator: redirect to admin login if not authenticated."""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            return redirect(url_for("admin_login", next=request.url))
        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# Admin auth routes
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    next_url = request.args.get("next") or url_for("index")
    if request.method == "POST":
        password = request.form.get("password", "")
        if ADMIN_PASSWORD and password == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(next_url)
        elif not ADMIN_PASSWORD:
            # No password configured: allow anyone (dev mode)
            session["is_admin"] = True
            return redirect(next_url)
        else:
            error = "密码错误，请重试。"
    return render_template("admin_login.html", error=error, next=next_url)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))


@app.context_processor
def inject_admin():
    return {"is_admin": is_admin()}


# ---------------------------------------------------------------------------
# Blog routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    db = get_db()
    articles = db.execute(
        "SELECT * FROM articles ORDER BY id DESC"
    ).fetchall()
    return render_template("index.html", articles=articles)


@app.route("/article/<int:article_id>")
def article(article_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM articles WHERE id = ?", (article_id,)
    ).fetchone()
    if row is None:
        abort(404)
    return render_template("article.html", article=row)


@app.route("/article/new", methods=["GET", "POST"])
def new_article():
    error = None
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        author = request.form.get("author", "").strip() or "博主"
        if not title:
            error = "文章标题不能为空"
        elif not content:
            error = "文章内容不能为空"
        else:
            db = get_db()
            db.execute(
                "INSERT INTO articles (title, content, author, created_at) VALUES (?, ?, ?, ?)",
                (title, content, author, now_str()),
            )
            db.commit()
            return redirect(url_for("index"))
    return render_template("new_article.html", error=error)


@app.route("/article/<int:article_id>/delete", methods=["POST"])
@admin_required
def delete_article(article_id):
    db = get_db()
    db.execute("DELETE FROM articles WHERE id = ?", (article_id,))
    db.commit()
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Forum routes
# ---------------------------------------------------------------------------

@app.route("/forum")
def forum():
    db = get_db()
    posts = db.execute(
        """
        SELECT p.*, COUNT(c.id) AS comment_count
        FROM posts p
        LEFT JOIN comments c ON c.post_id = p.id
        GROUP BY p.id
        ORDER BY p.id DESC
        """
    ).fetchall()
    return render_template("forum.html", posts=posts)


@app.route("/forum/post/<int:post_id>")
def post(post_id):
    db = get_db()
    row = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if row is None:
        abort(404)
    comments = db.execute(
        "SELECT * FROM comments WHERE post_id = ? ORDER BY id ASC", (post_id,)
    ).fetchall()
    return render_template("post.html", post=row, comments=comments)


@app.route("/forum/new", methods=["GET", "POST"])
def new_post():
    error = None
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        author = request.form.get("author", "").strip() or "匿名用户"
        if not title:
            error = "帖子标题不能为空"
        elif not content:
            error = "帖子内容不能为空"
        else:
            db = get_db()
            db.execute(
                "INSERT INTO posts (title, content, author, created_at) VALUES (?, ?, ?, ?)",
                (title, content, author, now_str()),
            )
            db.commit()
            return redirect(url_for("forum"))
    return render_template("new_post.html", error=error)


@app.route("/forum/post/<int:post_id>/comment", methods=["POST"])
def add_comment(post_id):
    db = get_db()
    row = db.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone()
    if row is None:
        abort(404)
    content = request.form.get("content", "").strip()
    author = request.form.get("author", "").strip() or "匿名用户"
    if content:
        db.execute(
            "INSERT INTO comments (post_id, content, author, created_at) VALUES (?, ?, ?, ?)",
            (post_id, content, author, now_str()),
        )
        db.commit()
    return redirect(url_for("post", post_id=post_id))


@app.route("/forum/post/<int:post_id>/delete", methods=["POST"])
@admin_required
def delete_post(post_id):
    db = get_db()
    db.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
    db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    db.commit()
    return redirect(url_for("forum"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, port=5000)
