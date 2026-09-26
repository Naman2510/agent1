-- GENERATED FILE — do not edit.
--
-- Dumped from a database built by `alembic upgrade head`, so this is the schema that actually
-- exists today. Regenerate with: scripts/dump_schema.sh
--
-- For the full *designed* schema, including the tables no phase has built yet, see db/schema.sql.


CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

CREATE TYPE public.ingest_status AS ENUM (
    'pending',
    'parsing',
    'embedding',
    'ready',
    'failed'
);

CREATE TYPE public.memory_kind AS ENUM (
    'observation',
    'profile_update',
    'topic_update'
);

CREATE TYPE public.message_role AS ENUM (
    'user',
    'assistant',
    'system',
    'tool'
);

CREATE TYPE public.plan_status AS ENUM (
    'active',
    'completed',
    'abandoned'
);

CREATE TYPE public.session_status AS ENUM (
    'active',
    'ended',
    'abandoned',
    'error'
);

CREATE TYPE public.tool_status AS ENUM (
    'ok',
    'error',
    'rejected',
    'timeout',
    'budget_exceeded'
);

CREATE TYPE public.user_role AS ENUM (
    'student',
    'admin'
);

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);

CREATE TABLE public.audit_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    actor_id uuid,
    action character varying(64) NOT NULL,
    target_type character varying(64),
    target_id character varying(64),
    ip_hash character varying(64),
    detail jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.document_chunks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid NOT NULL,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    heading_path text,
    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, content)) STORED,
    embedding public.vector(256),
    embedding_model text,
    token_count integer,
    page_start integer,
    page_end integer,
    section text,
    difficulty text,
    language text,
    metadata_ jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_document_chunks_ck_document_chunks_difficulty CHECK (((difficulty IS NULL) OR (difficulty = ANY (ARRAY['easy'::text, 'medium'::text, 'hard'::text]))))
);

CREATE TABLE public.documents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title text NOT NULL,
    subject text NOT NULL,
    topic text,
    semester smallint,
    language character varying(16) DEFAULT 'en'::character varying NOT NULL,
    source_path text NOT NULL,
    source_hash text NOT NULL,
    license text,
    page_count integer,
    ingest_status public.ingest_status DEFAULT 'pending'::public.ingest_status NOT NULL,
    metadata_ jsonb DEFAULT '{}'::jsonb NOT NULL,
    ingested_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.memory_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    student_id uuid NOT NULL,
    session_id uuid,
    message_id uuid,
    kind public.memory_kind NOT NULL,
    payload jsonb NOT NULL,
    confidence numeric(4,3),
    applied boolean DEFAULT false NOT NULL,
    rejection_reason text,
    extractor_version text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NOT NULL,
    turn_index integer NOT NULL,
    seq smallint DEFAULT '0'::smallint NOT NULL,
    role public.message_role NOT NULL,
    content text NOT NULL,
    unspoken_remainder text,
    language character varying(16),
    stt_confidence numeric(4,3),
    was_interrupted boolean DEFAULT false NOT NULL,
    spoken_prefix_chars integer,
    audio_ref text,
    token_usage jsonb,
    latency_ms jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    citations jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT ck_messages_ck_messages_interrupted_only_assistant CHECK (((NOT was_interrupted) OR (role = 'assistant'::public.message_role))),
    CONSTRAINT ck_messages_ck_messages_spoken_prefix_non_negative CHECK (((spoken_prefix_chars IS NULL) OR (spoken_prefix_chars >= 0)))
);

CREATE TABLE public.quiz_attempts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    quiz_id uuid NOT NULL,
    student_id uuid NOT NULL,
    answers jsonb NOT NULL,
    per_question jsonb DEFAULT '[]'::jsonb NOT NULL,
    score numeric(5,2),
    max_score numeric(5,2),
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone
);

CREATE TABLE public.quizzes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    student_id uuid NOT NULL,
    session_id uuid,
    subject text NOT NULL,
    topic text NOT NULL,
    difficulty text NOT NULL,
    language text DEFAULT 'en'::text NOT NULL,
    questions jsonb NOT NULL,
    source_chunk_ids uuid[] DEFAULT '{}'::uuid[] NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_quizzes_ck_quizzes_difficulty CHECK ((difficulty = ANY (ARRAY['easy'::text, 'medium'::text, 'hard'::text])))
);

CREATE TABLE public.refresh_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    token_hash text NOT NULL,
    family_id uuid NOT NULL,
    issued_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    user_agent character varying(256),
    CONSTRAINT ck_refresh_tokens_ck_refresh_tokens_expiry_after_issue CHECK ((expires_at > issued_at))
);

CREATE TABLE public.retrieval_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid,
    message_id uuid,
    query text NOT NULL,
    query_language text,
    retriever_config jsonb NOT NULL,
    candidate_ids uuid[] DEFAULT '{}'::uuid[] NOT NULL,
    chosen_ids uuid[] DEFAULT '{}'::uuid[] NOT NULL,
    scores jsonb,
    latency_ms integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    student_id uuid NOT NULL,
    status public.session_status DEFAULT 'active'::public.session_status NOT NULL,
    transport character varying(32) DEFAULT 'websocket'::character varying NOT NULL,
    client_info jsonb DEFAULT '{}'::jsonb NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    ended_at timestamp with time zone,
    turn_count integer DEFAULT 0 NOT NULL
);

CREATE TABLE public.student_profiles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    student_id uuid NOT NULL,
    digest text DEFAULT ''::text NOT NULL,
    learning_preferences jsonb DEFAULT '{}'::jsonb NOT NULL,
    explanation_style text,
    version integer DEFAULT 1 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.student_topics (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    student_id uuid NOT NULL,
    subject text NOT NULL,
    topic text NOT NULL,
    mastery numeric(4,3) DEFAULT 0.500 NOT NULL,
    confidence numeric(4,3) DEFAULT 0.100 NOT NULL,
    evidence_count integer DEFAULT 0 NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_student_topics_ck_student_topics_confidence_range CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric))),
    CONSTRAINT ck_student_topics_ck_student_topics_mastery_range CHECK (((mastery >= (0)::numeric) AND (mastery <= (1)::numeric)))
);

CREATE TABLE public.students (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    display_name character varying(120) NOT NULL,
    institution character varying(200),
    semester smallint,
    preferred_language character varying(16) DEFAULT 'auto'::character varying NOT NULL,
    consent_audio_retention boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_students_ck_students_language_allowed CHECK (((preferred_language)::text = ANY ((ARRAY['en'::character varying, 'hi'::character varying, 'hi-Latn'::character varying, 'ta'::character varying, 'auto'::character varying])::text[]))),
    CONSTRAINT ck_students_ck_students_semester_range CHECK (((semester IS NULL) OR ((semester >= 1) AND (semester <= 12))))
);

CREATE TABLE public.study_plan_items (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    plan_id uuid NOT NULL,
    day_index smallint NOT NULL,
    subject text NOT NULL,
    topic text NOT NULL,
    activity text NOT NULL,
    est_minutes smallint,
    completed_at timestamp with time zone
);

CREATE TABLE public.study_plans (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    student_id uuid NOT NULL,
    title text NOT NULL,
    goal text,
    start_date date NOT NULL,
    end_date date NOT NULL,
    status public.plan_status DEFAULT 'active'::public.plan_status NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_study_plans_ck_study_plans_date_order CHECK ((end_date >= start_date))
);

CREATE TABLE public.tool_calls (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NOT NULL,
    message_id uuid,
    turn_index integer NOT NULL,
    tool_name character varying(64) NOT NULL,
    arguments jsonb NOT NULL,
    result jsonb,
    status public.tool_status NOT NULL,
    error text,
    duration_ms integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email public.citext NOT NULL,
    password_hash text NOT NULL,
    role public.user_role DEFAULT 'student'::public.user_role NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT pk_audit_log PRIMARY KEY (id);

ALTER TABLE ONLY public.document_chunks
    ADD CONSTRAINT pk_document_chunks PRIMARY KEY (id);

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT pk_documents PRIMARY KEY (id);

ALTER TABLE ONLY public.memory_events
    ADD CONSTRAINT pk_memory_events PRIMARY KEY (id);

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT pk_messages PRIMARY KEY (id);

ALTER TABLE ONLY public.quiz_attempts
    ADD CONSTRAINT pk_quiz_attempts PRIMARY KEY (id);

ALTER TABLE ONLY public.quizzes
    ADD CONSTRAINT pk_quizzes PRIMARY KEY (id);

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT pk_refresh_tokens PRIMARY KEY (id);

ALTER TABLE ONLY public.retrieval_logs
    ADD CONSTRAINT pk_retrieval_logs PRIMARY KEY (id);

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT pk_sessions PRIMARY KEY (id);

ALTER TABLE ONLY public.student_profiles
    ADD CONSTRAINT pk_student_profiles PRIMARY KEY (id);

ALTER TABLE ONLY public.student_topics
    ADD CONSTRAINT pk_student_topics PRIMARY KEY (id);

ALTER TABLE ONLY public.students
    ADD CONSTRAINT pk_students PRIMARY KEY (id);

ALTER TABLE ONLY public.study_plan_items
    ADD CONSTRAINT pk_study_plan_items PRIMARY KEY (id);

ALTER TABLE ONLY public.study_plans
    ADD CONSTRAINT pk_study_plans PRIMARY KEY (id);

ALTER TABLE ONLY public.tool_calls
    ADD CONSTRAINT pk_tool_calls PRIMARY KEY (id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT pk_users PRIMARY KEY (id);

ALTER TABLE ONLY public.document_chunks
    ADD CONSTRAINT uq_document_chunks_doc_chunk UNIQUE (document_id, chunk_index);

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT uq_documents_source_hash UNIQUE (source_hash);

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT uq_messages_turn_seq UNIQUE (session_id, turn_index, seq);

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT uq_refresh_tokens_token_hash UNIQUE (token_hash);

ALTER TABLE ONLY public.student_profiles
    ADD CONSTRAINT uq_student_profiles_student_id UNIQUE (student_id);

ALTER TABLE ONLY public.student_topics
    ADD CONSTRAINT uq_student_topics_student_subject_topic UNIQUE (student_id, subject, topic);

ALTER TABLE ONLY public.students
    ADD CONSTRAINT uq_students_user_id UNIQUE (user_id);

ALTER TABLE ONLY public.study_plan_items
    ADD CONSTRAINT uq_study_plan_items_plan_day_topic UNIQUE (plan_id, day_index, subject, topic);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_email UNIQUE (email);

CREATE INDEX ix_audit_log_actor ON public.audit_log USING btree (actor_id, created_at);

CREATE INDEX ix_document_chunks_embedding ON public.document_chunks USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');

CREATE INDEX ix_document_chunks_filter ON public.document_chunks USING btree (language, difficulty);

CREATE INDEX ix_document_chunks_meta ON public.document_chunks USING gin (metadata_ jsonb_path_ops);

CREATE INDEX ix_document_chunks_trgm ON public.document_chunks USING gin (content public.gin_trgm_ops);

CREATE INDEX ix_document_chunks_tsv ON public.document_chunks USING gin (content_tsv);

CREATE INDEX ix_memory_events_student ON public.memory_events USING btree (student_id, created_at);

CREATE INDEX ix_messages_session_turn ON public.messages USING btree (session_id, turn_index, seq);

CREATE INDEX ix_quiz_attempts_student ON public.quiz_attempts USING btree (student_id, completed_at);

CREATE INDEX ix_refresh_tokens_family ON public.refresh_tokens USING btree (family_id);

CREATE INDEX ix_refresh_tokens_user_active ON public.refresh_tokens USING btree (user_id) WHERE (revoked_at IS NULL);

CREATE INDEX ix_retrieval_logs_session ON public.retrieval_logs USING btree (session_id, created_at);

CREATE INDEX ix_sessions_student_started ON public.sessions USING btree (student_id, started_at);

CREATE INDEX ix_student_topics_weak ON public.student_topics USING btree (student_id, mastery) WHERE (mastery < 0.5);

CREATE INDEX ix_tool_calls_name_status ON public.tool_calls USING btree (tool_name, status, created_at);

CREATE INDEX ix_tool_calls_session_turn ON public.tool_calls USING btree (session_id, turn_index);

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT fk_audit_log_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.document_chunks
    ADD CONSTRAINT fk_document_chunks_document_id_documents FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.memory_events
    ADD CONSTRAINT fk_memory_events_message_id_messages FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.memory_events
    ADD CONSTRAINT fk_memory_events_session_id_sessions FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.memory_events
    ADD CONSTRAINT fk_memory_events_student_id_students FOREIGN KEY (student_id) REFERENCES public.students(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT fk_messages_session_id_sessions FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.quiz_attempts
    ADD CONSTRAINT fk_quiz_attempts_quiz_id_quizzes FOREIGN KEY (quiz_id) REFERENCES public.quizzes(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.quiz_attempts
    ADD CONSTRAINT fk_quiz_attempts_student_id_students FOREIGN KEY (student_id) REFERENCES public.students(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.quizzes
    ADD CONSTRAINT fk_quizzes_session_id_sessions FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.quizzes
    ADD CONSTRAINT fk_quizzes_student_id_students FOREIGN KEY (student_id) REFERENCES public.students(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT fk_refresh_tokens_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.retrieval_logs
    ADD CONSTRAINT fk_retrieval_logs_message_id_messages FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.retrieval_logs
    ADD CONSTRAINT fk_retrieval_logs_session_id_sessions FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT fk_sessions_student_id_students FOREIGN KEY (student_id) REFERENCES public.students(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.student_profiles
    ADD CONSTRAINT fk_student_profiles_student_id_students FOREIGN KEY (student_id) REFERENCES public.students(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.student_topics
    ADD CONSTRAINT fk_student_topics_student_id_students FOREIGN KEY (student_id) REFERENCES public.students(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.students
    ADD CONSTRAINT fk_students_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.study_plan_items
    ADD CONSTRAINT fk_study_plan_items_plan_id_study_plans FOREIGN KEY (plan_id) REFERENCES public.study_plans(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.study_plans
    ADD CONSTRAINT fk_study_plans_student_id_students FOREIGN KEY (student_id) REFERENCES public.students(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tool_calls
    ADD CONSTRAINT fk_tool_calls_message_id_messages FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tool_calls
    ADD CONSTRAINT fk_tool_calls_session_id_sessions FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;

