CREATE DATABASE Research_Assistan_db;

\c Research_Assistan_db

CREATE TABLE IF NOT EXISTS research_cache (
    id SERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    query_text TEXT NOT NULL,
    content JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_type, query_text)
);

CREATE TABLE IF NOT EXISTS research_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    citations JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);