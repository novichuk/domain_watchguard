-- Domain Watchguard — database schema
-- Execute against PostgreSQL 14+

CREATE TABLE IF NOT EXISTS domains (
    id              SERIAL PRIMARY KEY,
    domain          VARCHAR(512) UNIQUE NOT NULL,
    is_active       BOOLEAN     DEFAULT TRUE,
    is_healthy      BOOLEAN,                        -- NULL = never checked
    is_current      BOOLEAN     DEFAULT FALSE,
    consecutive_ok  INTEGER     DEFAULT 0,
    total_downs     INTEGER     DEFAULT 0,
    total_ups       INTEGER     DEFAULT 0,
    total_downtime  BIGINT      DEFAULT 0,          -- seconds
    last_down_at    TIMESTAMPTZ,
    last_checked_at TIMESTAMPTZ,
    added_at        TIMESTAMPTZ DEFAULT NOW(),
    sort_order      INTEGER     DEFAULT 0
);

CREATE TABLE IF NOT EXISTS domain_events (
    id          SERIAL PRIMARY KEY,
    domain_id   INTEGER REFERENCES domains(id) ON DELETE CASCADE,
    event_type  VARCHAR(50) NOT NULL,               -- down / up / rotation_in / rotation_out
    details     TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS app_config (
    key        VARCHAR(100) PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_domains_active  ON domains(is_active);
CREATE INDEX IF NOT EXISTS idx_domains_current ON domains(is_current);
CREATE INDEX IF NOT EXISTS idx_events_domain   ON domain_events(domain_id);
CREATE INDEX IF NOT EXISTS idx_events_created  ON domain_events(created_at);

-- Proxy checker tables

CREATE TABLE IF NOT EXISTS proxies (
    id                   SERIAL PRIMARY KEY,
    airtable_id          VARCHAR(50) UNIQUE NOT NULL,
    proxy_url            TEXT NOT NULL,
    ip                   VARCHAR(100),
    port                 INTEGER,
    proxy_type           VARCHAR(10),
    is_healthy           BOOLEAN,
    consecutive_fails    INTEGER     DEFAULT 0,
    last_checked_at      TIMESTAMPTZ,
    last_down_at         TIMESTAMPTZ,
    last_expiry_alert_at TIMESTAMPTZ,
    created_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS proxy_events (
    id                SERIAL PRIMARY KEY,
    proxy_airtable_id VARCHAR(50) NOT NULL,
    event_type        VARCHAR(50) NOT NULL,
    details           TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proxies_airtable   ON proxies(airtable_id);
CREATE INDEX IF NOT EXISTS idx_proxy_events_created ON proxy_events(created_at);
