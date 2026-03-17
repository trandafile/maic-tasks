-- MAIC LAB Task Manager Supabase (PostgreSQL) Schema

-- 1. Users
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT,
    is_approved BOOLEAN DEFAULT FALSE,
    avatar_color TEXT
);

-- 2. Settings
CREATE TABLE IF NOT EXISTS settings (
    id SERIAL PRIMARY KEY,
    expiring_threshold_days INTEGER DEFAULT 7,
    deliverable_types JSONB DEFAULT '["paper", "layout", "prototype"]'::jsonb
);

-- 3. Projects
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    acronym TEXT,
    identifier TEXT,
    funding_agency TEXT,
    start_date DATE,
    end_date DATE,
    is_archived BOOLEAN DEFAULT FALSE
);

-- 4. Deliverables
CREATE TABLE IF NOT EXISTS deliverables (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT,
    type TEXT,
    status TEXT,
    deadline DATE,
    is_archived BOOLEAN DEFAULT FALSE
);

-- 5. Tasks
CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    sequence_id TEXT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    deliverable_id INTEGER REFERENCES deliverables(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    owner_email TEXT REFERENCES users(email),
    supervisor_email TEXT REFERENCES users(email),
    status TEXT,
    priority TEXT,
    estimate_hours REAL,
    deadline DATE,
    completion_date DATE,
    notes TEXT,
    sort_order INTEGER,
    is_archived BOOLEAN DEFAULT FALSE
);

-- 6. Subtasks
CREATE TABLE IF NOT EXISTS subtasks (
    id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    owner_email TEXT REFERENCES users(email),
    supervisor_email TEXT REFERENCES users(email),
    status TEXT,
    deadline DATE,
    notes TEXT,
    sort_order INTEGER,
    is_archived BOOLEAN DEFAULT FALSE
);

-- 7. Labels
CREATE TABLE IF NOT EXISTS labels (
    id SERIAL PRIMARY KEY,
    name TEXT,
    color TEXT
);

-- 8. Task Labels (Many-to-Many)
CREATE TABLE IF NOT EXISTS task_labels (
    task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    label_id INTEGER REFERENCES labels(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, label_id)
);

-- 9. Task Dependencies
CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on_task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    type TEXT,
    PRIMARY KEY (task_id, depends_on_task_id)
);

-- 10. Comments
CREATE TABLE IF NOT EXISTS comments (
    id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    author_email TEXT REFERENCES users(email),
    body TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_system_event BOOLEAN DEFAULT FALSE
);

-- Seed Initial Admin User
INSERT INTO users (email, name, role, is_approved, avatar_color)
VALUES ('luigi.boccia@unical.it', 'System Administrator', 'admin', TRUE, '#ff5733')
ON CONFLICT (email) DO NOTHING;

-- Seed Regular User
INSERT INTO users (email, name, role, is_approved, avatar_color)
VALUES ('user@maic.it', 'Regular User', 'user', TRUE, '#33c1ff')
ON CONFLICT (email) DO NOTHING;

-- Seed Default Settings
INSERT INTO settings (id, expiring_threshold_days, deliverable_types)
VALUES (1, 7, '["paper", "layout", "prototype"]'::jsonb)
ON CONFLICT (id) DO NOTHING;
