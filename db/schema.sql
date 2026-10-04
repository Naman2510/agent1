-- VaaniOS — design-reference schema (Phase 0)
--
-- This file documents the intended schema so it can be reviewed before any code exists.
-- It is NOT the migration source of truth: from Phase 1 onward, Alembic migrations under
-- backend/migrations/ are authoritative and this file is regenerated from the live schema.
--
-- Target: PostgreSQL 16 with pgvector >= 0.7 and pg_trgm.

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;

-- ---------------------------------------------------------------------------
-- Enumerations (values that gate application logic)
-- ---------------------------------------------------------------------------
CREATE TYPE user_role        AS ENUM ('student', 'admin');
CREATE TYPE session_status   AS ENUM ('active', 'ended', 'abandoned', 'error');
CREATE TYPE message_role     AS ENUM ('user', 'assistant', 'system', 'tool');
CREATE TYPE tool_status      AS ENUM ('ok', 'error', 'rejected', 'timeout', 'budget_exceeded');
CREATE TYPE ingest_status    AS ENUM ('pending', 'parsing', 'embedding', 'ready', 'failed');
CREATE TYPE plan_status      AS ENUM ('active', 'completed', 'abandoned');
CREATE TYPE memory_kind      AS ENUM ('observation', 'profile_update', 'topic_update');
CREATE TYPE eval_status      AS ENUM ('running', 'completed', 'failed');
CREATE TYPE exp_decision     AS ENUM ('adopt', 'reject', 'inconclusive', 'pending');

-- ---------------------------------------------------------------------------
-- Identity
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email           citext NOT NULL UNIQUE,
    password_hash   text NOT NULL,                  -- Argon2id; never bcrypt-by-default
    role            user_role NOT NULL DEFAULT 'student',
    is_active       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE refresh_tokens (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      text NOT NULL UNIQUE,           -- store the hash, never the token
    issued_at       timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    revoked_at      timestamptz,
    user_agent      text,
    CHECK (expires_at > issued_at)
);
CREATE INDEX idx_refresh_user_active ON refresh_tokens(user_id) WHERE revoked_at IS NULL;

CREATE TABLE students (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    display_name       text NOT NULL,
    institution        text,
    semester           smallint CHECK (semester BETWEEN 1 AND 12),
    preferred_language text NOT NULL DEFAULT 'en'
                       CHECK (preferred_language IN ('en','hi','hi-Latn','ta','auto')),
    consent_audio_retention boolean NOT NULL DEFAULT false,   -- DPDP: opt-in, default off
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Conversation
-- ---------------------------------------------------------------------------
CREATE TABLE sessions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id    uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    status        session_status NOT NULL DEFAULT 'active',
    transport     text NOT NULL DEFAULT 'websocket',
    client_info   jsonb NOT NULL DEFAULT '{}'::jsonb,   -- ua, sample rate, headphones hint
    started_at    timestamptz NOT NULL DEFAULT now(),
    ended_at      timestamptz,
    turn_count    integer NOT NULL DEFAULT 0
);
CREATE INDEX idx_sessions_student_started ON sessions(student_id, started_at DESC);

CREATE TABLE messages (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_index          integer NOT NULL,
    seq                 smallint NOT NULL DEFAULT 0,   -- ordering within a turn
    role                message_role NOT NULL,
    content             text NOT NULL,                 -- for interrupted turns: the SPOKEN prefix
    unspoken_remainder  text,                          -- debugging only; never replayed as context
    language            text,                          -- 'en' | 'hi' | 'hi-Latn' | 'ta' | 'mixed'
    stt_confidence      real,
    was_interrupted     boolean NOT NULL DEFAULT false,
    spoken_prefix_chars integer,
    audio_ref           text,                          -- object key; only with consent
    token_usage         jsonb,                         -- input/output/cache_read
    latency_ms          jsonb NOT NULL DEFAULT '{}'::jsonb,  -- the nine stage marks
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, turn_index, seq),
    CHECK (spoken_prefix_chars IS NULL OR spoken_prefix_chars >= 0),
    CHECK (NOT was_interrupted OR role = 'assistant')
);
CREATE INDEX idx_messages_session_turn ON messages(session_id, turn_index, seq);

CREATE TABLE tool_calls (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id   uuid REFERENCES messages(id) ON DELETE CASCADE,
    turn_index   integer NOT NULL,
    tool_name    text NOT NULL,
    arguments    jsonb NOT NULL,
    result       jsonb,
    status       tool_status NOT NULL,
    error        text,
    duration_ms  integer,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_tool_calls_name_status ON tool_calls(tool_name, status, created_at DESC);

CREATE TABLE retrieval_logs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       uuid REFERENCES sessions(id) ON DELETE CASCADE,
    message_id       uuid REFERENCES messages(id) ON DELETE CASCADE,
    query            text NOT NULL,
    query_language   text,
    retriever_config jsonb NOT NULL,      -- k, filters, fusion, reranker on/off, model ids
    candidate_ids    uuid[] NOT NULL DEFAULT '{}',
    chosen_ids       uuid[] NOT NULL DEFAULT '{}',
    scores           jsonb,
    latency_ms       integer,
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Long-term memory
-- ---------------------------------------------------------------------------
CREATE TABLE student_profiles (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id           uuid NOT NULL UNIQUE REFERENCES students(id) ON DELETE CASCADE,
    digest               text NOT NULL DEFAULT '',     -- short natural-language summary
    learning_preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
    explanation_style    text,
    version              integer NOT NULL DEFAULT 1,
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE student_topics (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id     uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject        text NOT NULL,
    topic          text NOT NULL,
    mastery        numeric(4,3) NOT NULL DEFAULT 0.500 CHECK (mastery BETWEEN 0 AND 1),
    confidence     numeric(4,3) NOT NULL DEFAULT 0.100 CHECK (confidence BETWEEN 0 AND 1),
    evidence_count integer NOT NULL DEFAULT 0,
    last_seen_at   timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (student_id, subject, topic)
);
CREATE INDEX idx_topics_weak ON student_topics(student_id, mastery) WHERE mastery < 0.5;

CREATE TABLE memory_events (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id        uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    session_id        uuid REFERENCES sessions(id) ON DELETE SET NULL,
    message_id        uuid REFERENCES messages(id) ON DELETE SET NULL,
    kind              memory_kind NOT NULL,
    payload           jsonb NOT NULL,        -- the proposed delta, verbatim
    confidence        numeric(4,3),
    applied           boolean NOT NULL DEFAULT false,
    rejection_reason  text,
    extractor_version text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_memory_events_student ON memory_events(student_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Study plans and quizzes
-- ---------------------------------------------------------------------------
CREATE TABLE study_plans (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    title      text NOT NULL,
    goal       text,
    start_date date NOT NULL,
    end_date   date NOT NULL,
    status     plan_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date)
);

CREATE TABLE study_plan_items (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id      uuid NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
    day_index    smallint NOT NULL,
    subject      text NOT NULL,
    topic        text NOT NULL,
    activity     text NOT NULL,
    est_minutes  smallint,
    completed_at timestamptz,
    UNIQUE (plan_id, day_index, subject, topic)
);

CREATE TABLE quizzes (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id       uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    session_id       uuid REFERENCES sessions(id) ON DELETE SET NULL,
    subject          text NOT NULL,
    topic            text NOT NULL,
    difficulty       text NOT NULL CHECK (difficulty IN ('easy','medium','hard')),
    language         text NOT NULL DEFAULT 'en',
    questions        jsonb NOT NULL,        -- [{id, prompt, expected, rubric, source_chunk_id}]
    source_chunk_ids uuid[] NOT NULL DEFAULT '{}',   -- grounding; empty = ungrounded, flagged in eval
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE quiz_attempts (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id       uuid NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    student_id    uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    answers       jsonb NOT NULL,
    per_question  jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{id, correct, score, feedback}]
    score         numeric(5,2),
    max_score     numeric(5,2),
    started_at    timestamptz NOT NULL DEFAULT now(),
    completed_at  timestamptz
);
CREATE INDEX idx_attempts_student ON quiz_attempts(student_id, completed_at DESC);

-- ---------------------------------------------------------------------------
-- RAG corpus
-- ---------------------------------------------------------------------------
CREATE TABLE documents (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title         text NOT NULL,
    subject       text NOT NULL,
    topic         text,
    semester      smallint,
    language      text NOT NULL DEFAULT 'en',
    source_path   text NOT NULL,
    source_hash   text NOT NULL UNIQUE,     -- sha256 of the raw file; makes ingest idempotent
    license       text,                     -- must be set before ingestion (see DATASET.md)
    page_count    integer,
    ingest_status ingest_status NOT NULL DEFAULT 'pending',
    metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
    ingested_at   timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_chunks (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     integer NOT NULL,
    content         text NOT NULL,
    heading_path    text,                   -- 'Unit 3 > Maxwell's Equations > Displacement Current'
    content_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    embedding       vector(768),            -- multilingual-e5-base; NULL until embedded
    embedding_model text,
    token_count     integer,
    page_start      integer,
    page_end        integer,
    section         text,
    difficulty      text CHECK (difficulty IS NULL OR difficulty IN ('easy','medium','hard')),
    language        text,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX idx_chunks_embedding ON document_chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_chunks_tsv      ON document_chunks USING gin (content_tsv);
CREATE INDEX idx_chunks_trgm     ON document_chunks USING gin (content gin_trgm_ops);
CREATE INDEX idx_chunks_meta     ON document_chunks USING gin (metadata jsonb_path_ops);
CREATE INDEX idx_chunks_filter   ON document_chunks(language, difficulty);

-- ---------------------------------------------------------------------------
-- Evaluation and experiments
-- ---------------------------------------------------------------------------
CREATE TABLE evaluation_runs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    suite           text NOT NULL,          -- stt | retrieval | agent | response | voice | e2e
    dataset_version text NOT NULL,
    config          jsonb NOT NULL,         -- providers, models, retriever settings, prompt version
    git_sha         text NOT NULL,
    mlflow_run_id   text,
    status          eval_status NOT NULL DEFAULT 'running',
    summary_metrics jsonb NOT NULL DEFAULT '{}'::jsonb,   -- one-way mirror of MLflow metrics
    case_count      integer,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    notes           text
);
CREATE INDEX idx_eval_runs_suite ON evaluation_runs(suite, started_at DESC);

CREATE TABLE evaluation_results (
    id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id   uuid NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    case_id  text NOT NULL,
    language text,
    input    jsonb NOT NULL,
    expected jsonb,
    actual   jsonb,
    metrics  jsonb NOT NULL DEFAULT '{}'::jsonb,
    passed   boolean,
    notes    text,
    UNIQUE (run_id, case_id)
);
CREATE INDEX idx_eval_results_failed ON evaluation_results(run_id) WHERE passed = false;

CREATE TABLE experiments (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug              text NOT NULL UNIQUE,      -- EXP-003
    title             text NOT NULL,
    hypothesis        text NOT NULL,
    variable_changed  text NOT NULL,             -- exactly ONE variable
    baseline_run_id   uuid REFERENCES evaluation_runs(id) ON DELETE SET NULL,
    candidate_run_id  uuid REFERENCES evaluation_runs(id) ON DELETE SET NULL,
    decision          exp_decision NOT NULL DEFAULT 'pending',
    rationale         text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    decided_at        timestamptz
);

CREATE TABLE audit_log (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id    uuid REFERENCES users(id) ON DELETE SET NULL,
    action      text NOT NULL,
    target_type text,
    target_id   text,
    ip_hash     text,          -- hashed, not raw
    detail      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_actor ON audit_log(actor_id, created_at DESC);
