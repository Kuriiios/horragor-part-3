CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS movies (
    id text PRIMARY KEY,
    tmdb_id text UNIQUE,
    imdb_id text UNIQUE,
    title text NOT NULL,
    normalized_title text NOT NULL,
    release_date date,
    overview text,
    tagline text,
    vote_average double precision CHECK (vote_average BETWEEN 0 AND 10),
    imdb_rating double precision CHECK (imdb_rating BETWEEN 0 AND 10),
    tomatometer_score double precision CHECK (tomatometer_score BETWEEN 0 AND 100),
    audience_score double precision CHECK (audience_score BETWEEN 0 AND 100),
    popularity double precision CHECK (popularity >= 0),
    poster_path text,
    budget bigint CHECK (budget >= 0),
    revenue bigint CHECK (revenue >= 0),
    runtime integer CHECK (runtime >= 0),
    overview_embedding vector(768),
    extra_attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sources (
    name text PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS movie_sources (
    movie_id text NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    source_name text NOT NULL REFERENCES sources(name) ON DELETE RESTRICT,
    source_record_id text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (movie_id, source_name)
);

CREATE TABLE IF NOT EXISTS genres (
    name text PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS movie_genres (
    movie_id text NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    genre_name text NOT NULL REFERENCES genres(name) ON DELETE RESTRICT,
    PRIMARY KEY (movie_id, genre_name)
);

CREATE TABLE IF NOT EXISTS people (
    id text PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE IF NOT EXISTS credits (
    id text PRIMARY KEY,
    movie_id text NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    person_id text NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    credit_type text NOT NULL CHECK (credit_type IN ('cast', 'crew')),
    role_name text NOT NULL DEFAULT '',
    billing_order integer,
    UNIQUE (movie_id, person_id, credit_type, role_name)
);

CREATE INDEX IF NOT EXISTS ix_movies_normalized_title ON movies(normalized_title);
CREATE INDEX IF NOT EXISTS ix_movies_release_date ON movies(release_date);
CREATE INDEX IF NOT EXISTS ix_movies_overview_embedding
    ON movies USING hnsw (overview_embedding vector_cosine_ops);

ALTER TABLE movies ENABLE ROW LEVEL SECURITY;
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE movie_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE genres ENABLE ROW LEVEL SECURITY;
ALTER TABLE movie_genres ENABLE ROW LEVEL SECURITY;
ALTER TABLE people ENABLE ROW LEVEL SECURITY;
ALTER TABLE credits ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;