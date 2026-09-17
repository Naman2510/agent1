-- GENERATED FILE — do not edit.
--
-- Dumped from a database built by `alembic upgrade head`, so this is the schema that actually
-- exists today. Regenerate with: scripts/dump_schema.sh
--
-- For the full *designed* schema, including the RAG, memory, quiz and evaluation tables that
-- later phases will add, see db/schema.sql.

CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;

CREATE TYPE public.message_role AS ENUM (
    'user',
    'assistant',
    'system',
    'tool'
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
    CONSTRAINT ck_messages_ck_messages_interrupted_only_assistant CHECK (((NOT was_interrupted) OR (role = 'assistant'::public.message_role))),
    CONSTRAINT ck_messages_ck_messages_spoken_prefix_non_negative CHECK (((spoken_prefix_chars IS NULL) OR (spoken_prefix_chars >= 0)))
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

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT pk_messages PRIMARY KEY (id);

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT pk_refresh_tokens PRIMARY KEY (id);

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT pk_sessions PRIMARY KEY (id);

ALTER TABLE ONLY public.students
    ADD CONSTRAINT pk_students PRIMARY KEY (id);

ALTER TABLE ONLY public.tool_calls
    ADD CONSTRAINT pk_tool_calls PRIMARY KEY (id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT pk_users PRIMARY KEY (id);

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT uq_messages_turn_seq UNIQUE (session_id, turn_index, seq);

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT uq_refresh_tokens_token_hash UNIQUE (token_hash);

ALTER TABLE ONLY public.students
    ADD CONSTRAINT uq_students_user_id UNIQUE (user_id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_email UNIQUE (email);

CREATE INDEX ix_audit_log_actor ON public.audit_log USING btree (actor_id, created_at);

CREATE INDEX ix_messages_session_turn ON public.messages USING btree (session_id, turn_index, seq);

CREATE INDEX ix_refresh_tokens_family ON public.refresh_tokens USING btree (family_id);

CREATE INDEX ix_refresh_tokens_user_active ON public.refresh_tokens USING btree (user_id) WHERE (revoked_at IS NULL);

CREATE INDEX ix_sessions_student_started ON public.sessions USING btree (student_id, started_at);

CREATE INDEX ix_tool_calls_name_status ON public.tool_calls USING btree (tool_name, status, created_at);

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT fk_audit_log_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT fk_messages_session_id_sessions FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT fk_refresh_tokens_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT fk_sessions_student_id_students FOREIGN KEY (student_id) REFERENCES public.students(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.students
    ADD CONSTRAINT fk_students_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tool_calls
    ADD CONSTRAINT fk_tool_calls_message_id_messages FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tool_calls
    ADD CONSTRAINT fk_tool_calls_session_id_sessions FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;
