"""SQLite database models for user accounts and project history."""

import sqlite3
import os
from datetime import datetime
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = Path(__file__).parent / "db" / "users.db"


def get_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            original_filename TEXT,
            original_path TEXT,
            machine_type TEXT,
            personality TEXT,
            catchphrase TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            style TEXT,
            expression TEXT,
            body_style TEXT,
            background TEXT,
            camera_angle TEXT,
            image_path TEXT,
            prompt_text TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()


# User operations

def create_user(email, password, name):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
            (email.lower().strip(), generate_password_hash(password), name.strip())
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
        conn.close()
        return dict(user)
    except sqlite3.IntegrityError:
        conn.close()
        return None


def authenticate_user(email, password):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    conn.close()
    if user and check_password_hash(user["password_hash"], password):
        return dict(user)
    return None


def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


# Project operations

def create_project(user_id, original_filename, original_path, machine_type="", personality="", catchphrase=""):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO projects (user_id, original_filename, original_path, machine_type, personality, catchphrase) VALUES (?,?,?,?,?,?)",
        (user_id, original_filename, original_path, machine_type, personality, catchphrase)
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def get_user_projects(user_id):
    conn = get_db()
    projects = conn.execute(
        "SELECT p.*, COUNT(g.id) as gen_count FROM projects p "
        "LEFT JOIN generations g ON g.project_id = p.id "
        "WHERE p.user_id = ? GROUP BY p.id ORDER BY p.created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(p) for p in projects]


def get_project(project_id, user_id):
    conn = get_db()
    project = conn.execute(
        "SELECT * FROM projects WHERE id = ? AND user_id = ?",
        (project_id, user_id)
    ).fetchone()
    if not project:
        conn.close()
        return None, []
    gens = conn.execute(
        "SELECT * FROM generations WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,)
    ).fetchall()
    conn.close()
    return dict(project), [dict(g) for g in gens]


def delete_project(project_id, user_id):
    conn = get_db()
    conn.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id))
    conn.commit()
    conn.close()


def rename_project(project_id, user_id, new_name):
    conn = get_db()
    conn.execute("UPDATE projects SET machine_type = ? WHERE id = ? AND user_id = ?",
                 (new_name.strip(), project_id, user_id))
    conn.commit()
    conn.close()


def delete_generation(gen_id, user_id):
    """Delete a generation if it belongs to user's project."""
    conn = get_db()
    row = conn.execute(
        "SELECT g.image_path FROM generations g JOIN projects p ON g.project_id = p.id "
        "WHERE g.id = ? AND p.user_id = ?", (gen_id, user_id)
    ).fetchone()
    if row:
        conn.execute("DELETE FROM generations WHERE id = ?", (gen_id,))
        conn.commit()
        # Delete file
        if row["image_path"]:
            p = Path(row["image_path"])
            if p.exists():
                p.unlink(missing_ok=True)
    conn.close()


# Generation operations

def add_generation(project_id, style, expression, body_style, background, camera_angle, image_path, prompt_text=""):
    conn = get_db()
    conn.execute(
        "INSERT INTO generations (project_id, style, expression, body_style, background, camera_angle, image_path, prompt_text) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (project_id, style, expression, body_style, background, camera_angle, image_path, prompt_text)
    )
    conn.commit()
    conn.close()


# Init on import
init_db()
