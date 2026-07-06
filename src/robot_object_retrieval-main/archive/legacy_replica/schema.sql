CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS objects;
DROP TABLE IF EXISTS locations;

CREATE TABLE locations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE objects (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(100) NOT NULL,
    location_id INTEGER NOT NULL REFERENCES locations(id),
    x DOUBLE PRECISION NOT NULL,
    y DOUBLE PRECISION NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'available',
    embedding VECTOR(__EMBEDDING_DIMENSION__)
);

CREATE INDEX idx_objects_category ON objects(category);
CREATE INDEX idx_objects_name ON objects(name);
CREATE INDEX idx_objects_location_id ON objects(location_id);
