PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('STUDENT', 'TEACHER', 'ADMIN')),
    email TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS departments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    color TEXT NOT NULL,
    background TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1)
);
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    teacher_id INTEGER NOT NULL REFERENCES users(id),
    department_id TEXT REFERENCES departments(id),
    is_demo INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1)),
    archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1)
);
CREATE TABLE IF NOT EXISTS class_sessions (
    id INTEGER PRIMARY KEY,
    course_id INTEGER NOT NULL REFERENCES courses(id),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    classroom TEXT NOT NULL,
    class_name TEXT NOT NULL,
    CHECK (ends_at > starts_at)
);
CREATE TABLE IF NOT EXISTS schedule_users (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    scheduled_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (session_id, user_id)
);
CREATE TABLE IF NOT EXISTS emoji_records (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
    emotion TEXT NOT NULL CHECK (emotion IN ('HAPPY', 'NEUTRAL', 'SAD', 'ANGRY', 'SURPRISED', 'FEAR', 'DISGUST')),
    source TEXT NOT NULL CHECK (source IN ('MANUAL', 'AI')),
    confidence REAL CHECK (confidence >= 0 AND confidence <= 1),
    device_id TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1)),
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (source <> 'AI' OR confidence IS NOT NULL),
    CHECK (source <> 'MANUAL' OR user_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_emoji_session_time ON emoji_records(session_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_emoji_user_time ON emoji_records(user_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_emoji_record_time ON emoji_records(recorded_at);
CREATE TABLE IF NOT EXISTS demo_seed_items (
    kind TEXT NOT NULL,
    seed_key TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    PRIMARY KEY (kind, seed_key)
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY,
    actor_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at);
CREATE TABLE IF NOT EXISTS auth_rate_limits (
    key TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL,
    reset_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS emoji_submission_keys (
    user_id INTEGER NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    record_id INTEGER NOT NULL UNIQUE REFERENCES emoji_records(id),
    PRIMARY KEY (user_id, request_id)
);

CREATE TABLE IF NOT EXISTS ai_frame_keys (
    actor_id INTEGER NOT NULL REFERENCES users(id),
    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
    request_id TEXT NOT NULL,
    frame_hash TEXT NOT NULL,
    result TEXT NOT NULL,
    PRIMARY KEY (actor_id, session_id, request_id)
);

CREATE TABLE IF NOT EXISTS ai_batch_keys (
    device_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
    payload_hash TEXT NOT NULL,
    result TEXT NOT NULL,
    PRIMARY KEY (device_id, batch_id)
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    nickname TEXT NOT NULL DEFAULT '' CHECK (length(nickname) <= 32),
    bio TEXT NOT NULL DEFAULT '' CHECK (length(bio) <= 160),
    interests TEXT NOT NULL DEFAULT '' CHECK (length(interests) <= 80),
    avatar_color TEXT NOT NULL DEFAULT 'sage' CHECK (avatar_color IN ('sage','sand','sky','lilac','rose')),
    major TEXT NOT NULL DEFAULT '' CHECK (length(major) <= 60),
    grade TEXT NOT NULL DEFAULT '' CHECK (length(grade) <= 20),
    study_goal TEXT NOT NULL DEFAULT '' CHECK (length(study_goal) <= 100),
    learning_style TEXT NOT NULL DEFAULT '' CHECK (learning_style IN ('','pair','questions','project','focus'))
);

CREATE TABLE IF NOT EXISTS buddy_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    low_user_id INTEGER NOT NULL REFERENCES users(id),
    high_user_id INTEGER NOT NULL REFERENCES users(id),
    requester_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','ACCEPTED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    accepted_at TEXT,
    UNIQUE (low_user_id, high_user_id),
    CHECK (low_user_id < high_user_id),
    CHECK (requester_id IN (low_user_id, high_user_id)),
    CHECK ((status='PENDING' AND accepted_at IS NULL) OR (status='ACCEPTED' AND accepted_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_buddy_high_user ON buddy_connections(high_user_id);

CREATE TABLE IF NOT EXISTS classroom_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
    author_id INTEGER NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('PACE','EXAMPLE','REPEAT','OTHER')),
    text TEXT NOT NULL DEFAULT '' CHECK (length(text) <= 300),
    reply TEXT NOT NULL DEFAULT '' CHECK (length(reply) <= 1000),
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','RESOLVED')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(author_id,request_id)
);
CREATE INDEX IF NOT EXISTS idx_question_session ON classroom_questions(session_id,status,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_question_author_time ON classroom_questions(author_id,created_at);

CREATE TABLE IF NOT EXISTS classroom_reflections (
    session_id INTEGER PRIMARY KEY REFERENCES class_sessions(id),
    reflection TEXT NOT NULL DEFAULT '' CHECK (length(reflection) <= 2000),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS personal_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    session_id INTEGER REFERENCES class_sessions(id),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 80),
    content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 5000),
    takeaway TEXT NOT NULL DEFAULT '' CHECK (length(takeaway) <= 300),
    next_step TEXT NOT NULL DEFAULT '' CHECK (length(next_step) <= 300),
    reviewed INTEGER NOT NULL DEFAULT 0 CHECK (reviewed IN (0,1)),
    reviewed_at TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((reviewed=0 AND reviewed_at IS NULL) OR (reviewed=1 AND reviewed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_personal_notes_owner ON personal_notes(user_id,reviewed,updated_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_personal_notes_session ON personal_notes(user_id,session_id);
CREATE TABLE IF NOT EXISTS personal_note_keys (
    user_id INTEGER NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    note_id INTEGER REFERENCES personal_notes(id) ON DELETE SET NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(user_id,request_id)
);
CREATE INDEX IF NOT EXISTS idx_personal_note_key_time ON personal_note_keys(user_id,created_at);

CREATE TABLE IF NOT EXISTS buddy_wall_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    author_id INTEGER NOT NULL REFERENCES users(id),
    content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 600),
    visibility TEXT NOT NULL DEFAULT 'ANONYMOUS' CHECK (visibility IN ('ANONYMOUS','REVEALABLE')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version>=1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wall_owner ON buddy_wall_messages(owner_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_wall_author ON buddy_wall_messages(author_id,created_at DESC,id DESC);
CREATE TABLE IF NOT EXISTS buddy_wall_keys (
    author_id INTEGER NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    message_id INTEGER REFERENCES buddy_wall_messages(id) ON DELETE SET NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(author_id,request_id)
);
CREATE INDEX IF NOT EXISTS idx_wall_key_time ON buddy_wall_keys(author_id,created_at);

CREATE TABLE IF NOT EXISTS session_join_codes (
    session_id INTEGER PRIMARY KEY REFERENCES class_sessions(id),
    code TEXT NOT NULL UNIQUE CHECK (length(code)=8),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    expires_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version>=1),
    updated_at TEXT NOT NULL,
    created_by INTEGER NOT NULL REFERENCES users(id),
    last_request_id TEXT NOT NULL,
    last_payload_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS course_enrollments (
    course_id INTEGER NOT NULL REFERENCES courses(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    joined_at TEXT NOT NULL,
    PRIMARY KEY(course_id,user_id)
);
CREATE INDEX IF NOT EXISTS idx_course_enrollment_user ON course_enrollments(user_id,course_id);

CREATE TABLE IF NOT EXISTS user_avatars (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    image BLOB NOT NULL CHECK (length(image) BETWEEN 1 AND 200000),
    digest TEXT NOT NULL CHECK (length(digest)=64),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classroom_guides (
    session_id INTEGER PRIMARY KEY REFERENCES class_sessions(id),
    title TEXT NOT NULL DEFAULT '' CHECK (length(title)<=80),
    content TEXT NOT NULL DEFAULT '' CHECK (length(content)<=3000),
    practice TEXT NOT NULL DEFAULT '' CHECK (length(practice)<=1500),
    published_title TEXT NOT NULL DEFAULT '',
    published_content TEXT NOT NULL DEFAULT '',
    published_practice TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    version INTEGER NOT NULL CHECK (version>=1),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teaching_session_keys (
    user_id INTEGER NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
    payload_hash TEXT NOT NULL,
    PRIMARY KEY(user_id,request_id)
);

CREATE TABLE IF NOT EXISTS demo_access_sessions (
    token_hash TEXT PRIMARY KEY,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS leave_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
    student_id INTEGER NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('SICK','PERSONAL','OTHER')),
    reason TEXT NOT NULL CHECK (length(reason) BETWEEN 2 AND 500),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED','CANCELLED')),
    reply TEXT NOT NULL DEFAULT '' CHECK (length(reply)<=500),
    reviewer_id INTEGER REFERENCES users(id),
    reviewed_at TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version>=1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(student_id,request_id),
    CHECK ((status IN ('PENDING','CANCELLED') AND reviewer_id IS NULL AND reviewed_at IS NULL AND reply='')
       OR (status IN ('APPROVED','REJECTED') AND reviewer_id IS NOT NULL AND reviewed_at IS NOT NULL)),
    CHECK (status<>'REJECTED' OR length(reply)>0)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_leave_active ON leave_requests(student_id,session_id) WHERE status IN ('PENDING','APPROVED');
CREATE INDEX IF NOT EXISTS idx_leave_student ON leave_requests(student_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_leave_session ON leave_requests(session_id,status);

CREATE TABLE IF NOT EXISTS removed_departments (id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS course_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
    student_id INTEGER NOT NULL REFERENCES users(id),
    clarity INTEGER NOT NULL CHECK (clarity BETWEEN 1 AND 5),
    pace INTEGER NOT NULL CHECK (pace BETWEEN 1 AND 5),
    engagement INTEGER NOT NULL CHECK (engagement BETWEEN 1 AND 5),
    gain INTEGER NOT NULL CHECK (gain BETWEEN 1 AND 5),
    comment TEXT NOT NULL DEFAULT '' CHECK(length(comment)<=1000),
    version INTEGER NOT NULL CHECK(version>=1),
    is_demo INTEGER NOT NULL DEFAULT 0 CHECK(is_demo IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(session_id,student_id)
);
CREATE INDEX IF NOT EXISTS idx_evaluation_session ON course_evaluations(session_id,is_demo);
CREATE TABLE IF NOT EXISTS evaluation_keys (
    student_id INTEGER NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    result TEXT NOT NULL,
    PRIMARY KEY(student_id,request_id)
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('LEAVE','QUESTION','GUIDE','BUDDY')),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    target_tab TEXT NOT NULL,
    session_id INTEGER REFERENCES class_sessions(id),
    course_id INTEGER REFERENCES courses(id),
    read_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(user_id,event_key)
);
CREATE INDEX IF NOT EXISTS idx_notifications_owner ON notifications(user_id,read_at,id DESC);
CREATE TABLE IF NOT EXISTS course_creation_keys (
    user_id INTEGER NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    course_id INTEGER NOT NULL REFERENCES courses(id),
    payload_hash TEXT NOT NULL,
    PRIMARY KEY (user_id, request_id)
);

CREATE TABLE IF NOT EXISTS session_privacy (
    session_id INTEGER PRIMARY KEY REFERENCES class_sessions(id),
    mode TEXT NOT NULL CHECK(mode IN ('STANDARD','ANONYMOUS','AGGREGATE')),
    version INTEGER NOT NULL CHECK(version>=1),
    updated_at TEXT NOT NULL,
    updated_by INTEGER NOT NULL REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS emotion_insight_rules (
    session_id INTEGER PRIMARY KEY REFERENCES class_sessions(id),
    bucket_minutes INTEGER NOT NULL CHECK(bucket_minutes IN (1,5,10)),
    min_records INTEGER NOT NULL CHECK(min_records BETWEEN 3 AND 1000),
    concern_ratio REAL NOT NULL CHECK(concern_ratio BETWEEN 0.3 AND 1),
    consecutive_windows INTEGER NOT NULL CHECK(consecutive_windows BETWEEN 2 AND 6),
    version INTEGER NOT NULL CHECK(version >= 1),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emotion_insight_entries (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
    kind TEXT NOT NULL CHECK(kind IN ('PHASE','ACTION')),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
    content TEXT NOT NULL CHECK(length(content) <= 2000),
    start_minute INTEGER NOT NULL CHECK(start_minute >= 0),
    end_minute INTEGER NOT NULL CHECK(end_minute >= start_minute),
    status TEXT NOT NULL CHECK(status IN ('PLANNED','DONE','CANCELLED')),
    outcome TEXT NOT NULL DEFAULT '' CHECK(length(outcome) <= 2000),
    version INTEGER NOT NULL CHECK(version >= 1),
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    request_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    UNIQUE(session_id,request_id)
);
CREATE INDEX IF NOT EXISTS idx_insight_entries_session ON emotion_insight_entries(session_id,start_minute,id);

CREATE TABLE IF NOT EXISTS lab_studies (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    question TEXT NOT NULL,
    tags TEXT NOT NULL,
    definition TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1),
    archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
    request_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(owner_id,request_id)
);
CREATE INDEX IF NOT EXISTS idx_lab_studies_owner ON lab_studies(owner_id,archived,updated_at);
CREATE TABLE IF NOT EXISTS lab_jobs (
    id INTEGER PRIMARY KEY,
    study_id INTEGER NOT NULL REFERENCES lab_studies(id),
    owner_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    definition TEXT NOT NULL,
    study_version INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
    progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
    attempts INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
    lease_token TEXT,
    lease_until TEXT,
    error_code TEXT,
    request_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    report_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(owner_id,request_id)
);
CREATE INDEX IF NOT EXISTS idx_lab_jobs_claim ON lab_jobs(state,lease_until,created_at);
CREATE TABLE IF NOT EXISTS lab_job_events (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES lab_jobs(id),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    progress INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_events_job ON lab_job_events(job_id,id);
CREATE TABLE IF NOT EXISTS lab_reports (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL UNIQUE REFERENCES lab_jobs(id),
    study_id INTEGER NOT NULL REFERENCES lab_studies(id),
    owner_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    definition TEXT NOT NULL,
    result TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','REVIEWED','ARCHIVED')),
    bookmarked INTEGER NOT NULL DEFAULT 0 CHECK(bookmarked IN (0,1)),
    conclusion TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_reports_owner ON lab_reports(owner_id,status,created_at);
CREATE TABLE IF NOT EXISTS lab_annotations (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES lab_reports(id),
    section TEXT NOT NULL CHECK(section IN ('FINDING','CONTEXT','LIMITATION','NEXT_STEP')),
    content TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1),
    request_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(report_id,request_id)
);

CREATE TABLE IF NOT EXISTS feedback_cases (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
    author_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    emotion TEXT NOT NULL,
    reasons TEXT NOT NULL,
    impact TEXT NOT NULL CHECK(impact IN ('LOW','MEDIUM','HIGH')),
    topic_minute INTEGER,
    linked_record_id INTEGER REFERENCES emoji_records(id) ON DELETE SET NULL,
    state TEXT NOT NULL DEFAULT 'NEW' CHECK(state IN ('NEW','ACKNOWLEDGED','IN_PROGRESS','WAITING_STUDENT','WAITING_REVIEW','RESOLVED','WITHDRAWN')),
    priority TEXT NOT NULL DEFAULT 'NORMAL' CHECK(priority IN ('NORMAL','HIGH')),
    tags TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1,
    is_demo INTEGER NOT NULL CHECK(is_demo IN (0,1)),
    acknowledged_at TEXT,
    first_response_at TEXT,
    resolved_at TEXT,
    resolution TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_session_state ON feedback_cases(session_id,state,updated_at);
CREATE INDEX IF NOT EXISTS idx_feedback_author ON feedback_cases(author_id,updated_at);
CREATE TABLE IF NOT EXISTS feedback_messages (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES feedback_cases(id),
    actor_id INTEGER NOT NULL REFERENCES users(id),
    actor_role TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK(visibility IN ('SHARED','STAFF')),
    content TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_messages_case ON feedback_messages(case_id,id);
CREATE TABLE IF NOT EXISTS feedback_events (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES feedback_cases(id),
    actor_id INTEGER REFERENCES users(id),
    actor_role TEXT NOT NULL,
    code TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    detail TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'SHARED' CHECK(visibility IN ('SHARED','STAFF')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_events_case ON feedback_events(case_id,id);
CREATE TABLE IF NOT EXISTS feedback_commands (
    actor_id INTEGER NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(actor_id,request_id)
);
CREATE TABLE IF NOT EXISTS feedback_reviews (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES feedback_cases(id),
    prompt TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'OPEN' CHECK(state IN ('OPEN','ANSWERED','CANCELLED')),
    due_at TEXT NOT NULL,
    opened_by INTEGER NOT NULL REFERENCES users(id),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    closed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_single_open_review ON feedback_reviews(case_id) WHERE state='OPEN';
CREATE INDEX IF NOT EXISTS idx_feedback_review_due ON feedback_reviews(state,due_at,id);
CREATE TABLE IF NOT EXISTS feedback_review_reminders (
    review_id INTEGER PRIMARY KEY REFERENCES feedback_reviews(id) ON DELETE CASCADE,
    last_reminded_at TEXT NOT NULL,
    reminder_count INTEGER NOT NULL CHECK(reminder_count >= 1)
);
CREATE TABLE IF NOT EXISTS feedback_review_answers (
    id INTEGER PRIMARY KEY,
    review_id INTEGER NOT NULL UNIQUE REFERENCES feedback_reviews(id),
    outcome TEXT NOT NULL CHECK(outcome IN ('HELPED','PARTLY','UNCHANGED')),
    emotion TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback_groups (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback_group_members (
    group_id INTEGER NOT NULL REFERENCES feedback_groups(id),
    case_id INTEGER NOT NULL REFERENCES feedback_cases(id),
    PRIMARY KEY(group_id,case_id)
);
CREATE TABLE IF NOT EXISTS feedback_templates (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    reason TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
    uses INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback_policies (
    course_id INTEGER PRIMARY KEY REFERENCES courses(id),
    response_hours INTEGER NOT NULL,
    review_days INTEGER NOT NULL,
    submit_grace_hours INTEGER NOT NULL,
    daily_case_limit INTEGER NOT NULL,
    reopen_days INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback_watches (
    user_id INTEGER NOT NULL REFERENCES users(id),
    case_id INTEGER NOT NULL REFERENCES feedback_cases(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY(user_id,case_id)
);
CREATE TABLE IF NOT EXISTS feedback_adjustments (
    case_id INTEGER NOT NULL REFERENCES feedback_cases(id),
    adjustment_id INTEGER NOT NULL REFERENCES emotion_insight_entries(id) ON DELETE CASCADE,
    public_summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(case_id,adjustment_id)
);
CREATE TABLE IF NOT EXISTS feedback_inbox (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    case_id INTEGER NOT NULL REFERENCES feedback_cases(id),
    event_key TEXT NOT NULL,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT,
    UNIQUE(user_id,event_key)
);
CREATE INDEX IF NOT EXISTS idx_feedback_inbox_owner ON feedback_inbox(user_id,read_at,id);
CREATE TABLE IF NOT EXISTS feedback_saved_views (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    filters TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
