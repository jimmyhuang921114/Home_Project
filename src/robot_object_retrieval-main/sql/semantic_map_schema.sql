CREATE TABLE IF NOT EXISTS semantic_map_imports (
    id SERIAL PRIMARY KEY,
    map_id VARCHAR(255) NOT NULL,
    map_version VARCHAR(255) NOT NULL,
    frame_id VARCHAR(255) NOT NULL,
    source_next_id INTEGER NOT NULL,
    object_count INTEGER NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE semantic_map_imports
ADD COLUMN IF NOT EXISTS map_id VARCHAR(255);

ALTER TABLE semantic_map_imports
ADD COLUMN IF NOT EXISTS map_version VARCHAR(255);

CREATE TABLE IF NOT EXISTS semantic_map_objects (
    id SERIAL PRIMARY KEY,
    import_id INTEGER NOT NULL REFERENCES semantic_map_imports(id),
    source_id VARCHAR(255) NOT NULL,
    frame_id VARCHAR(255) NOT NULL,
    class_name VARCHAR(255) NOT NULL,
    x DOUBLE PRECISION NOT NULL,
    y DOUBLE PRECISION NOT NULL,
    z DOUBLE PRECISION NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    observe_count INTEGER NOT NULL,
    embedding VECTOR(__EMBEDDING_DIMENSION__) NOT NULL,
    UNIQUE (frame_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_semantic_map_objects_class_name
ON semantic_map_objects(class_name);

CREATE INDEX IF NOT EXISTS idx_semantic_map_objects_frame_id
ON semantic_map_objects(frame_id);

CREATE TABLE IF NOT EXISTS semantic_map_regions (
    id SERIAL PRIMARY KEY,
    frame_id VARCHAR(255) NOT NULL,
    region_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    geometry_type VARCHAR(32) NOT NULL,
    min_x DOUBLE PRECISION NOT NULL,
    max_x DOUBLE PRECISION NOT NULL,
    min_y DOUBLE PRECISION NOT NULL,
    max_y DOUBLE PRECISION NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (frame_id, region_id)
);

CREATE INDEX IF NOT EXISTS idx_semantic_map_regions_frame_id
ON semantic_map_regions(frame_id);
