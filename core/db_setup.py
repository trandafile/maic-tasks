import sqlite3
import os
import random

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "maic_lab.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Create tables
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT,
            is_approved BOOLEAN,
            avatar_color TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            expiring_threshold_days INTEGER DEFAULT 7,
            deliverable_types TEXT
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            acronym TEXT,
            identifier TEXT,
            funding_agency TEXT,
            start_date DATE,
            end_date DATE,
            is_archived BOOLEAN DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS deliverables (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            name TEXT,
            type TEXT,
            status TEXT,
            deadline DATE,
            description TEXT,
            supervisor_email TEXT,
            is_archived BOOLEAN DEFAULT 0,
            FOREIGN KEY(project_id) REFERENCES projects(id),
            FOREIGN KEY(supervisor_email) REFERENCES users(email)
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY,
            sequence_id TEXT,
            project_id INTEGER,
            deliverable_id INTEGER,
            name TEXT NOT NULL,
            owner_email TEXT,
            supervisor_email TEXT,
            status TEXT,
            priority TEXT,
            estimate_hours REAL,
            deadline DATE,
            completion_date DATE,
            notes TEXT,
            sort_order INTEGER,
            is_archived BOOLEAN DEFAULT 0,
            FOREIGN KEY(project_id) REFERENCES projects(id),
            FOREIGN KEY(deliverable_id) REFERENCES deliverables(id),
            FOREIGN KEY(owner_email) REFERENCES users(email),
            FOREIGN KEY(supervisor_email) REFERENCES users(email)
        );

        CREATE TABLE IF NOT EXISTS subtasks (
            id INTEGER PRIMARY KEY,
            task_id INTEGER,
            name TEXT NOT NULL,
            owner_email TEXT,
            supervisor_email TEXT,
            status TEXT,
            deadline DATE,
            notes TEXT,
            sort_order INTEGER,
            is_archived BOOLEAN DEFAULT 0,
            FOREIGN KEY(task_id) REFERENCES tasks(id),
            FOREIGN KEY(owner_email) REFERENCES users(email),
            FOREIGN KEY(supervisor_email) REFERENCES users(email)
        );

        CREATE TABLE IF NOT EXISTS labels (
            id INTEGER PRIMARY KEY,
            name TEXT,
            color TEXT
        );

        CREATE TABLE IF NOT EXISTS task_labels (
            task_id INTEGER,
            label_id INTEGER,
            FOREIGN KEY(task_id) REFERENCES tasks(id),
            FOREIGN KEY(label_id) REFERENCES labels(id),
            PRIMARY KEY (task_id, label_id)
        );

        CREATE TABLE IF NOT EXISTS task_dependencies (
            task_id INTEGER,
            depends_on_task_id INTEGER,
            type TEXT,
            FOREIGN KEY(task_id) REFERENCES tasks(id),
            FOREIGN KEY(depends_on_task_id) REFERENCES tasks(id),
            PRIMARY KEY (task_id, depends_on_task_id)
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY,
            task_id INTEGER,
            author_email TEXT,
            body TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_system_event BOOLEAN DEFAULT 0,
            FOREIGN KEY(task_id) REFERENCES tasks(id),
            FOREIGN KEY(author_email) REFERENCES users(email)
        );
    """)
    conn.commit()
    conn.close()

def generate_avatar_color():
    return "#{:06x}".format(random.randint(0, 0xFFFFFF))

def seed_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Seed Admin User
    cursor.execute('''
        INSERT OR IGNORE INTO users (email, name, role, is_approved, avatar_color)
        VALUES (?, ?, ?, ?, ?)
    ''', ('luigi.boccia@unical.it', 'System Administrator', 'admin', True, generate_avatar_color()))

    # Seed Regular User
    cursor.execute('''
        INSERT OR IGNORE INTO users (email, name, role, is_approved, avatar_color)
        VALUES (?, ?, ?, ?, ?)
    ''', ('user@maic.it', 'Regular User', 'user', True, generate_avatar_color()))
    
    # Initialize settings if not exists
    cursor.execute('SELECT COUNT(*) FROM settings')
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO settings (id, expiring_threshold_days, deliverable_types)
            VALUES (?, ?, ?)
        ''', (1, 7, '["paper", "layout", "prototype"]'))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    seed_db()
    print("Database initialized and seeded successfully.")
