-- FDA FAERS Analytics Platform — PostgreSQL Schema
-- Apply: psql -U faers_user -d faers -f database/schema.sql

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- Fuzzy text search on drug names
CREATE EXTENSION IF NOT EXISTS unaccent;     -- Remove accents in drug names
CREATE EXTENSION IF NOT EXISTS btree_gin;    -- GIN index on scalar types

-- DEMO — Demographics (one row per deduplicated case)
CREATE TABLE IF NOT EXISTS faers_demo (
    report_id           BIGINT      NOT NULL,
    caseid              BIGINT      NOT NULL,
    caseversion         INT,
    quarter             VARCHAR(10) NOT NULL,    -- e.g. '2026q1'
    i_f_code            CHAR(1),                -- I=Initial, F=Follow-up
    event_dt            DATE,                   -- Date adverse event occurred
    fda_dt              DATE,                   -- Date FDA received report
    rept_cod            VARCHAR(10),            -- EXP/PER/DIR/MAN/PHY
    age_years           DOUBLE PRECISION,       -- Normalized to decimal years
    sex                 VARCHAR(10),            -- Male/Female/Unknown
    weight_kg           DOUBLE PRECISION,       -- Normalized to kg
    age_group           VARCHAR(50),            -- Neonate/Child/Adult/Elderly/etc.
    reporter_country    VARCHAR(5),             -- 2-letter ISO
    occr_country        VARCHAR(5),             -- 2-letter ISO
    occp_cod            VARCHAR(5),             -- MD/PH/CN/LW/OT etc.
    extended_attributes JSONB DEFAULT '{}'::jsonb, -- Escape hatch for schema drift

    PRIMARY KEY (report_id)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_demo_caseid
    ON faers_demo(caseid);
CREATE INDEX IF NOT EXISTS idx_demo_quarter
    ON faers_demo(quarter);
CREATE INDEX IF NOT EXISTS idx_demo_event_dt
    ON faers_demo(event_dt);
CREATE INDEX IF NOT EXISTS idx_demo_country
    ON faers_demo(reporter_country, occr_country);
CREATE INDEX IF NOT EXISTS idx_demo_age
    ON faers_demo(age_years);
CREATE INDEX IF NOT EXISTS idx_demo_quarter_country
    ON faers_demo(quarter, reporter_country);

-- 2. DRUG — Drug information (many per case)
CREATE TABLE IF NOT EXISTS faers_drug (
    id                  BIGSERIAL   PRIMARY KEY,
    report_id           BIGINT      NOT NULL REFERENCES faers_demo(report_id) ON DELETE CASCADE,
    caseid              BIGINT      NOT NULL,
    drug_seq            INT,
    quarter             VARCHAR(10) NOT NULL,
    role_cod            CHAR(2),                -- PS/SS/C/I
    drug_role           VARCHAR(30),            -- Human-readable role
    drugname            TEXT,                   -- Original drug name (brand)
    drugname_clean      TEXT,                   -- Normalized (UPPERCASE, trimmed)
    prod_ai             TEXT,                   -- Active ingredient (original)
    prod_ai_clean       TEXT,                   -- Active ingredient (normalized)
    route               VARCHAR(100),           -- Route of administration (raw)
    route_clean         VARCHAR(100),           -- Route (normalized)
    dose_amt            DOUBLE PRECISION,
    dose_unit           VARCHAR(20),
    dose_form           VARCHAR(100),
    dose_freq           VARCHAR(100),
    nda_num             VARCHAR(20),            -- FDA NDA/BLA application number
    extended_attributes JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_drug_primaryid
    ON faers_drug(report_id);
CREATE INDEX IF NOT EXISTS idx_drug_primaryid_role
    ON faers_drug(report_id, role_cod);
CREATE INDEX IF NOT EXISTS idx_drug_quarter
    ON faers_drug(quarter);
CREATE INDEX IF NOT EXISTS idx_drug_role
    ON faers_drug(role_cod);

-- GIN trigram indexes for fuzzy drug name search (ILIKE '%drug%')
CREATE INDEX IF NOT EXISTS idx_drug_name_trgm
    ON faers_drug USING gin(drugname_clean gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_drug_prodai_trgm
    ON faers_drug USING gin(prod_ai_clean gin_trgm_ops);

-- 3. REAC — Adverse Reactions (many per case)
CREATE TABLE IF NOT EXISTS faers_reac (
    id                  BIGSERIAL   PRIMARY KEY,
    report_id           BIGINT      NOT NULL REFERENCES faers_demo(report_id) ON DELETE CASCADE,
    caseid              BIGINT      NOT NULL,
    quarter             VARCHAR(10) NOT NULL,
    pt                  TEXT        NOT NULL,   -- MedDRA Preferred Term (original)
    pt_clean            TEXT,                   -- MedDRA PT (title-cased)
    extended_attributes JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_reac_primaryid
    ON faers_reac(report_id);
CREATE INDEX IF NOT EXISTS idx_reac_quarter
    ON faers_reac(quarter);
CREATE INDEX IF NOT EXISTS idx_reac_pt
    ON faers_reac(pt_clean);
CREATE INDEX IF NOT EXISTS idx_reac_pt_trgm
    ON faers_reac USING gin(pt_clean gin_trgm_ops);

-- 4. OUTC — Patient Outcomes (many per case)
CREATE TABLE IF NOT EXISTS faers_outc (
    id                  BIGSERIAL   PRIMARY KEY,
    report_id           BIGINT      NOT NULL REFERENCES faers_demo(report_id) ON DELETE CASCADE,
    caseid              BIGINT      NOT NULL,
    quarter             VARCHAR(10) NOT NULL,
    outc_cod            VARCHAR(5)  NOT NULL,   -- DE/LT/HO/DS/CA/RI/OT
    outcome_label       TEXT,                   -- Human-readable label
    extended_attributes JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_outc_primaryid
    ON faers_outc(report_id);
CREATE INDEX IF NOT EXISTS idx_outc_cod
    ON faers_outc(outc_cod);
CREATE INDEX IF NOT EXISTS idx_outc_primaryid_cod
    ON faers_outc(report_id, outc_cod);

-- 5. THER — Therapy Dates
CREATE TABLE IF NOT EXISTS faers_ther (
    id                  BIGSERIAL   PRIMARY KEY,
    report_id           BIGINT      NOT NULL REFERENCES faers_demo(report_id) ON DELETE CASCADE,
    caseid              BIGINT      NOT NULL,
    drug_seq            INT,
    quarter             VARCHAR(10) NOT NULL,
    start_dt            DATE,
    end_dt              DATE,
    dur_days            DOUBLE PRECISION,        -- Duration normalized to days
    extended_attributes JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_ther_primaryid
    ON faers_ther(report_id);
CREATE INDEX IF NOT EXISTS idx_ther_primaryid_seq
    ON faers_ther(report_id, drug_seq);

-- 6. INDI — Drug Indications (what drug was prescribed for)
CREATE TABLE IF NOT EXISTS faers_indi (
    id                  BIGSERIAL   PRIMARY KEY,
    report_id           BIGINT      NOT NULL REFERENCES faers_demo(report_id) ON DELETE CASCADE,
    caseid              BIGINT      NOT NULL,
    drug_seq            INT,
    quarter             VARCHAR(10) NOT NULL,
    indi_pt             TEXT,                   -- MedDRA indication (original)
    indi_pt_clean       TEXT,                   -- MedDRA indication (title-cased)
    extended_attributes JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_indi_primaryid
    ON faers_indi(report_id);
CREATE INDEX IF NOT EXISTS idx_indi_pt_trgm
    ON faers_indi USING gin(indi_pt_clean gin_trgm_ops);

-- 7. RPSR — Report Sources
CREATE TABLE IF NOT EXISTS faers_rpsr (
    id                  BIGSERIAL   PRIMARY KEY,
    report_id           BIGINT      NOT NULL REFERENCES faers_demo(report_id) ON DELETE CASCADE,
    caseid              BIGINT      NOT NULL,
    quarter             VARCHAR(10) NOT NULL,
    rpsr_cod            VARCHAR(10),            -- FGN/OTC/LIT/CSM/DUP/HP/UF/CR/DDL
    extended_attributes JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_rpsr_primaryid
    ON faers_rpsr(report_id);

-- 8. Scaling: Quarter Partitions View (for partition planning)
-- Track all loaded quarters and their metadata
CREATE TABLE IF NOT EXISTS faers_quarter_metadata (
    quarter             VARCHAR(10) PRIMARY KEY,
    loaded_at           TIMESTAMP DEFAULT NOW(),
    demo_rows           INT,
    drug_rows           INT,
    reac_rows           INT,
    outc_rows           INT,
    total_rows          INT,
    load_seconds        FLOAT,
    data_source_url     TEXT
);

-- 9. ANALYSIS SUPPORT: Drug name mapping table
-- For resolving brand names → generic names

CREATE TABLE IF NOT EXISTS drug_name_mappings (
    id                  BIGSERIAL   PRIMARY KEY,
    brand_name          TEXT        NOT NULL,
    generic_name        TEXT,
    nda_num             VARCHAR(20),
    atc_code            VARCHAR(10),            -- WHO ATC Classification
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dnm_brand_trgm
    ON drug_name_mappings USING gin(brand_name gin_trgm_ops);

-- 10. NLQ Query Log (for analytics on what users ask)
CREATE TABLE IF NOT EXISTS nlq_query_log (
    id                  BIGSERIAL   PRIMARY KEY,
    query_text          TEXT        NOT NULL,
    generated_sql       TEXT,
    response_time_ms    INT,
    rows_returned       INT,
    from_cache          BOOLEAN DEFAULT false,
    error_message       TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nlq_created
    ON nlq_query_log(created_at DESC);

-- Verify schema
DO $$
BEGIN
    RAISE NOTICE 'FAERS Schema created successfully.';
    RAISE NOTICE 'Tables: faers_demo, faers_drug, faers_reac, faers_outc, faers_ther, faers_indi, faers_rpsr';
    RAISE NOTICE 'Next step: Run materialized_views.sql';
END $$;
