"""Product data: accounts, sessions, saved trips, favourites, places seen, reviews, reports
and the admin audit log, in PostgreSQL (TRAVELMATE_DATABASE_URL=postgresql://…) or, with no
URL, one SQLite file.

Queries are written once with `?` placeholders; `Db` adapts them for psycopg.

Security notes:
- Passwords are hashed with scrypt and a per-user salt; never stored or logged in clear.
- Session and password-reset tokens are random 32-byte values; only their SHA-256 is stored,
  so a copy of the database cannot be used to sign in.
- Every query is parameterised. Calls are synchronous; the API runs them in a worker thread.
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

SESSION_TTL_S = 30 * 24 * 3600
RESET_TTL_S = 30 * 60
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'locked')),
    interests TEXT NOT NULL DEFAULT '[]', created_at DOUBLE PRECISION NOT NULL, last_login DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at DOUBLE PRECISION NOT NULL, expires_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS resets (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at DOUBLE PRECISION NOT NULL, used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, title TEXT NOT NULL,
    request TEXT NOT NULL, result TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS trips_by_user ON trips(user_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS places (
    id TEXT PRIMARY KEY, data TEXT NOT NULL, hidden INTEGER NOT NULL DEFAULT 0, admin_note TEXT NOT NULL DEFAULT '',
    first_seen DOUBLE PRECISION NOT NULL, last_seen DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS favorites (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, place_id TEXT NOT NULL REFERENCES places(id),
    created_at DOUBLE PRECISION NOT NULL, PRIMARY KEY (user_id, place_id)
);
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY, place_id TEXT NOT NULL REFERENCES places(id),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5), text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'hidden')),
    moderation_note TEXT NOT NULL DEFAULT '', created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL,
    UNIQUE (place_id, user_id)
);
CREATE INDEX IF NOT EXISTS reviews_by_place ON reviews(place_id, status);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY, review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, reason TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0, created_at DOUBLE PRECISION NOT NULL, UNIQUE (review_id, user_id)
);
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, title TEXT NOT NULL,
    state TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS chats_by_user ON chats(user_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS audit (
    id {AUTO_ID}, actor_id TEXT, action TEXT NOT NULL, target TEXT NOT NULL, at DOUBLE PRECISION NOT NULL
);
"""


try:  # PostgreSQL driver is optional (extra "postgres")
    import psycopg
    from psycopg.rows import dict_row

    INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)
except ImportError:  # pragma: no cover - exercised only without the extra
    psycopg = None
    INTEGRITY_ERRORS = (sqlite3.IntegrityError,)


def is_postgres_url(value):
    return str(value).startswith(("postgresql://", "postgres://"))


class Db:
    """One connection with the same interface on SQLite and PostgreSQL; commits on success."""

    def __init__(self, conn, postgres):
        self.conn, self.postgres = conn, postgres

    def sql(self, statement):
        if self.postgres:
            return statement.replace("?", "%s").replace("GROUP_CONCAT(", "string_agg(")
        return statement

    def execute(self, statement, params=()):
        return self.conn.execute(self.sql(statement), params)

    def executemany(self, statement, rows):
        if self.postgres:
            with self.conn.cursor() as cursor:
                cursor.executemany(self.sql(statement), rows)
        else:
            self.conn.executemany(statement, rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()

    def close(self):
        self.conn.close()


class StoreError(Exception):
    """A business-rule failure with a message safe to show to the user."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    try:
        _, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **SCRYPT)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(row):
    return {"id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"],
            "status": row["status"], "interests": json.loads(row["interests"]), "created_at": row["created_at"],
            "last_login": row["last_login"]}


class Store:
    def __init__(self, location, admin_email=""):
        """location: a postgresql:// URL, or a path to a SQLite file."""
        self.postgres = is_postgres_url(location)
        if self.postgres and psycopg is None:
            raise ValueError("PostgreSQL needs the postgres extra: uv sync --extra postgres")
        self.location = str(location) if self.postgres else Path(location)
        self.admin_email = admin_email.strip().casefold()
        schema = SCHEMA.replace("{AUTO_ID}", "BIGSERIAL PRIMARY KEY" if self.postgres
                                else "INTEGER PRIMARY KEY AUTOINCREMENT")
        with closing(self.connect()) as db, db:
            if self.postgres:
                db.conn.execute(schema)
            else:
                db.conn.executescript(schema)

    @property
    def backend(self):
        return "postgresql" if self.postgres else "sqlite"

    def connect(self):
        if self.postgres:
            return Db(psycopg.connect(self.location, row_factory=dict_row, connect_timeout=10), True)
        conn = sqlite3.connect(self.location, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return Db(conn, False)

    def audit(self, db, actor_id, action, target):
        db.execute("INSERT INTO audit (actor_id, action, target, at) VALUES (?, ?, ?, ?)",
                   (actor_id, action, target, time.time()))

    # --- accounts --------------------------------------------------------------------------

    def signup(self, email, password, name):
        email = email.strip().casefold()
        role = "admin" if self.admin_email and email == self.admin_email else "user"
        user_id = str(uuid.uuid4())
        with closing(self.connect()) as db, db:
            try:
                db.execute(
                    "INSERT INTO users (id, email, name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, email, name.strip(), hash_password(password), role, time.time()))
            except INTEGRITY_ERRORS:
                raise StoreError("Email này đã có tài khoản.", 409) from None
            self.audit(db, user_id, "signup", user_id)
        return self.login(email, password)

    def login(self, email, password):
        email = email.strip().casefold()
        with closing(self.connect()) as db, db:
            row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row is None or not check_password(password, row["password_hash"]):
                if row is None:
                    hash_password(password)  # same cost either way: no account enumeration by timing
                raise StoreError("Email hoặc mật khẩu không đúng.", 401)
            if row["status"] == "locked":
                raise StoreError("Tài khoản đang bị khoá. Liên hệ quản trị viên.", 403)
            token = secrets.token_urlsafe(32)
            now = time.time()
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (token_hash(token), row["id"], now, now + SESSION_TTL_S))
            db.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, row["id"]))
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            row = db.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
        return token, public_user(row)

    def user_for_token(self, token):
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id "
                "WHERE token_hash = ? AND expires_at > ? AND users.status = 'active'",
                (token_hash(token), time.time())).fetchone()
        return public_user(row) if row else None

    def logout(self, token):
        with closing(self.connect()) as db, db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))

    def get_user(self, user_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise StoreError("Không tìm thấy người dùng.", 404)
        return public_user(row)

    def update_profile(self, user_id, name=None, interests=None):
        with closing(self.connect()) as db, db:
            if name is not None:
                db.execute("UPDATE users SET name = ? WHERE id = ?", (name.strip(), user_id))
            if interests is not None:
                db.execute("UPDATE users SET interests = ? WHERE id = ?",
                           (json.dumps(interests, ensure_ascii=False), user_id))
        return self.get_user(user_id)

    def change_password(self, user_id, current, new, keep_token=None):
        with closing(self.connect()) as db, db:
            row = db.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None or not check_password(current, row["password_hash"]):
                raise StoreError("Mật khẩu hiện tại không đúng.", 400)
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), user_id))
            # Sign out every other device.
            db.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                       (user_id, token_hash(keep_token or "")))
            self.audit(db, user_id, "change_password", user_id)

    def delete_account(self, user_id, password):
        with closing(self.connect()) as db, db:
            row = db.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None or not check_password(password, row["password_hash"]):
                raise StoreError("Mật khẩu không đúng.", 400)
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self.audit(db, None, "delete_account", user_id)

    def create_reset(self, email=None, user_id=None, actor_id=None):
        """Return (user, token) for a password reset, or (None, None) for an unknown email."""
        with closing(self.connect()) as db, db:
            if user_id:
                row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            else:
                row = db.execute("SELECT * FROM users WHERE email = ?", ((email or "").strip().casefold(),)).fetchone()
            if row is None:
                return None, None
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO resets VALUES (?, ?, ?, 0)", (token_hash(token), row["id"], time.time() + RESET_TTL_S))
            self.audit(db, actor_id or row["id"], "reset_requested", row["id"])
        return public_user(row), token

    def reset_password(self, token, password):
        with closing(self.connect()) as db, db:
            row = db.execute("SELECT * FROM resets WHERE token_hash = ? AND used = 0 AND expires_at > ?",
                             (token_hash(token), time.time())).fetchone()
            if row is None:
                raise StoreError("Link đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.", 400)
            db.execute("UPDATE resets SET used = 1 WHERE token_hash = ?", (row["token_hash"],))
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), row["user_id"]))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
            self.audit(db, row["user_id"], "reset_password", row["user_id"])

    # --- places seen by the app ---------------------------------------------------------------

    def remember_places(self, places):
        """Upsert place snapshots (a Place model's JSON) so detail pages, favourites and reviews have data."""
        if not places:
            return
        now = time.time()
        with closing(self.connect()) as db, db:
            db.executemany(
                "INSERT INTO places (id, data, first_seen, last_seen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, last_seen = excluded.last_seen",
                [(p["id"], json.dumps(p, ensure_ascii=False), now, now) for p in places])

    def hidden_place_ids(self):
        with closing(self.connect()) as db:
            return {r["id"] for r in db.execute("SELECT id FROM places WHERE hidden = 1")}

    def place(self, place_id, viewer=None):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM places WHERE id = ?", (place_id,)).fetchone()
            if row is None or (row["hidden"] and (viewer or {}).get("role") != "admin"):
                raise StoreError("Không tìm thấy địa điểm.", 404)
            stats = db.execute("SELECT COUNT(*) AS n, AVG(rating) AS avg FROM reviews "
                               "WHERE place_id = ? AND status = 'approved'", (place_id,)).fetchone()
            reviews = db.execute(
                "SELECT reviews.*, users.name AS author FROM reviews JOIN users ON users.id = reviews.user_id "
                "WHERE reviews.place_id = ? AND (reviews.status = 'approved' OR reviews.user_id = ?) "
                "ORDER BY reviews.updated_at DESC LIMIT 50",
                (place_id, (viewer or {}).get("id", ""))).fetchall()
            favorite = bool(viewer) and db.execute(
                "SELECT 1 FROM favorites WHERE user_id = ? AND place_id = ?", (viewer["id"], place_id)).fetchone()
        return {
            "place": json.loads(row["data"]), "hidden": bool(row["hidden"]), "admin_note": row["admin_note"],
            "review_count": stats["n"], "average_rating": None if stats["avg"] is None else round(float(stats["avg"]), 1),
            "reviews": [self.review_view(r, viewer) for r in reviews], "favorite": bool(favorite),
        }

    @staticmethod
    def review_view(row, viewer=None):
        mine = bool(viewer) and row["user_id"] == viewer["id"]
        return {"id": row["id"], "place_id": row["place_id"], "rating": row["rating"], "text": row["text"],
                "status": row["status"], "author": row["author"], "mine": mine,
                "moderation_note": row["moderation_note"] if mine else "", "updated_at": row["updated_at"]}

    # --- favourites --------------------------------------------------------------------------

    def favorites(self, user_id):
        with closing(self.connect()) as db:
            rows = db.execute("SELECT places.data FROM favorites JOIN places ON places.id = favorites.place_id "
                              "WHERE favorites.user_id = ? AND places.hidden = 0 ORDER BY favorites.created_at DESC",
                              (user_id,)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def set_favorite(self, user_id, place_id, on):
        with closing(self.connect()) as db, db:
            if on:
                if db.execute("SELECT 1 FROM places WHERE id = ? AND hidden = 0", (place_id,)).fetchone() is None:
                    raise StoreError("Không tìm thấy địa điểm.", 404)
                db.execute("INSERT INTO favorites VALUES (?, ?, ?) ON CONFLICT DO NOTHING", (user_id, place_id, time.time()))
            else:
                db.execute("DELETE FROM favorites WHERE user_id = ? AND place_id = ?", (user_id, place_id))

    # --- trips -------------------------------------------------------------------------------

    def save_trip(self, user_id, request, result, title):
        trip_id = str(uuid.uuid4())
        now = time.time()
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO trips VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (trip_id, user_id, title, json.dumps(request, ensure_ascii=False),
                        json.dumps(result, ensure_ascii=False), now, now))
        return self.trip(user_id, trip_id)

    def trips(self, user_id):
        with closing(self.connect()) as db:
            rows = db.execute("SELECT * FROM trips WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [self.trip_view(r, full=False) for r in rows]

    def trip(self, user_id, trip_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)).fetchone()
        if row is None:
            raise StoreError("Không tìm thấy chuyến đi.", 404)
        return self.trip_view(row)

    @staticmethod
    def trip_view(row, full=True):
        request, result = json.loads(row["request"]), json.loads(row["result"])
        view = {"id": row["id"], "title": row["title"], "destination": request.get("destination"),
                "start_date": request.get("start_date"), "end_date": request.get("end_date"),
                "days": len(result.get("draft", {}).get("days", [])), "created_at": row["created_at"],
                "updated_at": row["updated_at"]}
        if full:
            view.update(request=request, result=result)
        return view

    def update_trip(self, user_id, trip_id, title=None, result=None):
        with closing(self.connect()) as db, db:
            if db.execute("SELECT 1 FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)).fetchone() is None:
                raise StoreError("Không tìm thấy chuyến đi.", 404)
            if title is not None:
                db.execute("UPDATE trips SET title = ? WHERE id = ?", (title, trip_id))
            if result is not None:
                db.execute("UPDATE trips SET result = ? WHERE id = ?", (json.dumps(result, ensure_ascii=False), trip_id))
            db.execute("UPDATE trips SET updated_at = ? WHERE id = ?", (time.time(), trip_id))
        return self.trip(user_id, trip_id)

    def delete_trip(self, user_id, trip_id):
        with closing(self.connect()) as db, db:
            if db.execute("DELETE FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)).rowcount == 0:
                raise StoreError("Không tìm thấy chuyến đi.", 404)

    # --- chats --------------------------------------------------------------------------------

    def save_chat(self, user_id, chat_id, title, state):
        now = time.time()
        with closing(self.connect()) as db, db:
            owner = db.execute("SELECT user_id FROM chats WHERE id = ?", (chat_id,)).fetchone()
            if owner is not None and owner["user_id"] != user_id:
                raise StoreError("Không tìm thấy cuộc trò chuyện.", 404)
            db.execute(
                "INSERT INTO chats VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET state = excluded.state, "
                "updated_at = excluded.updated_at", (chat_id, user_id, title, json.dumps(state, ensure_ascii=False), now, now))

    def chats(self, user_id):
        with closing(self.connect()) as db:
            rows = db.execute("SELECT id, title, created_at, updated_at FROM chats WHERE user_id = ? "
                              "ORDER BY updated_at DESC LIMIT 50", (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def chat(self, user_id, chat_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM chats WHERE id = ? AND user_id = ?", (chat_id, user_id)).fetchone()
        if row is None:
            raise StoreError("Không tìm thấy cuộc trò chuyện.", 404)
        return {"id": row["id"], "title": row["title"], "state": json.loads(row["state"]),
                "updated_at": row["updated_at"]}

    def delete_chat(self, user_id, chat_id):
        with closing(self.connect()) as db, db:
            if db.execute("DELETE FROM chats WHERE id = ? AND user_id = ?", (chat_id, user_id)).rowcount == 0:
                raise StoreError("Không tìm thấy cuộc trò chuyện.", 404)

    # --- reviews and reports -----------------------------------------------------------------

    def upsert_review(self, user_id, place_id, rating, text):
        now = time.time()
        with closing(self.connect()) as db, db:
            if db.execute("SELECT 1 FROM places WHERE id = ? AND hidden = 0", (place_id,)).fetchone() is None:
                raise StoreError("Không tìm thấy địa điểm.", 404)
            db.execute(
                "INSERT INTO reviews (id, place_id, user_id, rating, text, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(place_id, user_id) DO UPDATE SET rating = excluded.rating, "
                "text = excluded.text, status = 'pending', moderation_note = '', updated_at = excluded.updated_at",
                (str(uuid.uuid4()), place_id, user_id, rating, text.strip(), now, now))
            row = db.execute("SELECT reviews.*, users.name AS author FROM reviews JOIN users ON users.id = reviews.user_id "
                             "WHERE reviews.place_id = ? AND reviews.user_id = ?", (place_id, user_id)).fetchone()
        return self.review_view(row, {"id": user_id})

    def delete_review(self, user_id, place_id):
        with closing(self.connect()) as db, db:
            if db.execute("DELETE FROM reviews WHERE place_id = ? AND user_id = ?", (place_id, user_id)).rowcount == 0:
                raise StoreError("Bạn chưa đánh giá địa điểm này.", 404)

    def my_reviews(self, user_id):
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT reviews.*, users.name AS author, places.data AS place FROM reviews "
                "JOIN users ON users.id = reviews.user_id JOIN places ON places.id = reviews.place_id "
                "WHERE reviews.user_id = ? ORDER BY reviews.updated_at DESC", (user_id,)).fetchall()
        return [{**self.review_view(r, {"id": user_id}), "place_name": json.loads(r["place"])["name"]} for r in rows]

    def report_review(self, user_id, review_id, reason):
        with closing(self.connect()) as db, db:
            row = db.execute("SELECT user_id FROM reviews WHERE id = ? AND status = 'approved'", (review_id,)).fetchone()
            if row is None:
                raise StoreError("Không tìm thấy đánh giá.", 404)
            if row["user_id"] == user_id:
                raise StoreError("Bạn không thể báo cáo đánh giá của chính mình.", 400)
            try:
                db.execute("INSERT INTO reports VALUES (?, ?, ?, ?, 0, ?)",
                           (str(uuid.uuid4()), review_id, user_id, reason.strip(), time.time()))
            except INTEGRITY_ERRORS:
                raise StoreError("Bạn đã báo cáo đánh giá này.", 409) from None

    # --- admin -------------------------------------------------------------------------------

    def stats(self):
        with closing(self.connect()) as db:
            one = lambda sql: db.execute(sql.replace("COUNT(*)", "COUNT(*) AS n", 1)).fetchone()["n"]  # noqa: E731
            recent = db.execute("SELECT audit.*, users.email AS actor FROM audit LEFT JOIN users ON users.id = actor_id "
                                "ORDER BY audit.id DESC LIMIT 15").fetchall()
            return {
                "users": one("SELECT COUNT(*) FROM users"),
                "admins": one("SELECT COUNT(*) FROM users WHERE role = 'admin'"),
                "locked_users": one("SELECT COUNT(*) FROM users WHERE status = 'locked'"),
                "trips": one("SELECT COUNT(*) FROM trips"),
                "places": one("SELECT COUNT(*) FROM places"),
                "hidden_places": one("SELECT COUNT(*) FROM places WHERE hidden = 1"),
                "reviews": one("SELECT COUNT(*) FROM reviews"),
                "pending_reviews": one("SELECT COUNT(*) FROM reviews WHERE status = 'pending'"),
                "open_reports": one("SELECT COUNT(*) FROM reports WHERE resolved = 0"),
                "recent": [{"action": r["action"], "target": r["target"], "actor": r["actor"], "at": r["at"]}
                           for r in recent],
            }

    def users(self, query=""):
        like = f"%{query.strip().casefold()}%"
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT users.*, (SELECT COUNT(*) FROM trips WHERE trips.user_id = users.id) AS trip_count, "
                "(SELECT COUNT(*) FROM reviews WHERE reviews.user_id = users.id) AS review_count FROM users "
                "WHERE lower(email) LIKE ? OR lower(name) LIKE ? ORDER BY created_at DESC LIMIT 200",
                (like, like)).fetchall()
        return [{**public_user(r), "trip_count": r["trip_count"], "review_count": r["review_count"]} for r in rows]

    def admin_update_user(self, actor_id, user_id, role=None, status=None):
        if user_id == actor_id and (role == "user" or status == "locked"):
            raise StoreError("Bạn không thể tự hạ quyền hoặc tự khoá tài khoản của mình.", 400)
        with closing(self.connect()) as db, db:
            if db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                raise StoreError("Không tìm thấy người dùng.", 404)
            if role is not None:
                db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
                self.audit(db, actor_id, f"set_role:{role}", user_id)
            if status is not None:
                db.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
                if status == "locked":
                    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
                self.audit(db, actor_id, f"set_status:{status}", user_id)
        return self.get_user(user_id)

    def admin_places(self, query="", hidden=None):
        like = f"%{query.strip().casefold()}%"
        sql = ("SELECT places.*, (SELECT COUNT(*) FROM reviews WHERE reviews.place_id = places.id) AS review_count, "
               "(SELECT COUNT(*) FROM favorites WHERE favorites.place_id = places.id) AS favorite_count "
               "FROM places WHERE lower(data) LIKE ?")
        args = [like]
        if hidden is not None:
            sql += " AND hidden = ?"
            args.append(int(hidden))
        with closing(self.connect()) as db:
            rows = db.execute(sql + " ORDER BY last_seen DESC LIMIT 200", args).fetchall()
        return [{"place": json.loads(r["data"]), "hidden": bool(r["hidden"]), "admin_note": r["admin_note"],
                 "review_count": r["review_count"], "favorite_count": r["favorite_count"],
                 "last_seen": r["last_seen"]} for r in rows]

    def admin_update_place(self, actor_id, place_id, hidden=None, admin_note=None):
        with closing(self.connect()) as db, db:
            if db.execute("SELECT 1 FROM places WHERE id = ?", (place_id,)).fetchone() is None:
                raise StoreError("Không tìm thấy địa điểm.", 404)
            if hidden is not None:
                db.execute("UPDATE places SET hidden = ? WHERE id = ?", (int(hidden), place_id))
                self.audit(db, actor_id, "hide_place" if hidden else "show_place", place_id)
            if admin_note is not None:
                db.execute("UPDATE places SET admin_note = ? WHERE id = ?", (admin_note.strip(), place_id))
                self.audit(db, actor_id, "note_place", place_id)
        return self.place(place_id, {"role": "admin", "id": actor_id})

    def moderation_queue(self):
        with closing(self.connect()) as db:
            pending = db.execute(
                "SELECT reviews.*, users.name AS author, users.email AS author_email, places.data AS place "
                "FROM reviews JOIN users ON users.id = reviews.user_id JOIN places ON places.id = reviews.place_id "
                "WHERE reviews.status = 'pending' ORDER BY reviews.updated_at").fetchall()
            reported = db.execute(
                "SELECT reviews.*, users.name AS author, users.email AS author_email, places.data AS place, "
                "COUNT(reports.id) AS report_count, GROUP_CONCAT(reports.reason, ' | ') AS reasons "
                "FROM reports JOIN reviews ON reviews.id = reports.review_id JOIN users ON users.id = reviews.user_id "
                "JOIN places ON places.id = reviews.place_id WHERE reports.resolved = 0 "
                "GROUP BY reviews.id, users.name, users.email, places.data ORDER BY MIN(reports.created_at)").fetchall()

        def view(row, extra=None):
            return {**self.review_view(row), "author_email": row["author_email"],
                    "place_name": json.loads(row["place"])["name"], **(extra or {})}

        return {"pending": [view(r) for r in pending],
                "reported": [view(r, {"report_count": r["report_count"], "reasons": r["reasons"]}) for r in reported]}

    def moderate(self, actor_id, review_id, action, note=""):
        status = {"approve": "approved", "reject": "rejected", "hide": "hidden"}[action]
        with closing(self.connect()) as db, db:
            if db.execute("SELECT 1 FROM reviews WHERE id = ?", (review_id,)).fetchone() is None:
                raise StoreError("Không tìm thấy đánh giá.", 404)
            db.execute("UPDATE reviews SET status = ?, moderation_note = ? WHERE id = ?", (status, note.strip(), review_id))
            db.execute("UPDATE reports SET resolved = 1 WHERE review_id = ?", (review_id,))
            self.audit(db, actor_id, f"moderate:{action}", review_id)
