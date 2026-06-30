-- FDA FAERS — Materialized Views for <5s Analytics
-- These views pre-compute the most common expensive queries.
-- They are refreshed nightly or after each quarter load.
-- Apply AFTER loading data: psql -f database/materialized_views.sql

-- VIEW 0: Cross-Quarter Case Deduplication (Foundation)
-- Cases can be updated in later quarters. This ensures we only
-- count the single latest version of a case across all partitions.

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_latest_cases AS
SELECT caseid, MAX(report_id) AS report_id
FROM faers_demo
GROUP BY caseid;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_lc_caseid
    ON mv_latest_cases(caseid);
CREATE INDEX IF NOT EXISTS idx_mv_lc_reportid
    ON mv_latest_cases(report_id);

-- VIEW 1: Drug-Reaction Pairs
-- The most fundamental query in FAERS: "What reactions happen with drug X?"

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_drug_reaction_pairs AS
SELECT
    d.drugname_clean,
    d.prod_ai_clean,
    d.role_cod,
    d.drug_role,
    r.pt_clean          AS reaction_term,
    d.quarter,
    COUNT(DISTINCT d.report_id) AS report_count
FROM faers_drug d
JOIN faers_reac r ON d.report_id = r.report_id
JOIN mv_latest_cases lc ON d.report_id = lc.report_id
WHERE d.drugname_clean IS NOT NULL
  AND d.drugname_clean != ''
  AND r.pt_clean IS NOT NULL
  AND r.pt_clean != ''
GROUP BY
    d.drugname_clean, d.prod_ai_clean, d.role_cod, d.drug_role,
    r.pt_clean, d.quarter;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_drp_unique
    ON mv_drug_reaction_pairs(drugname_clean, prod_ai_clean, role_cod, drug_role, reaction_term, quarter);
CREATE INDEX IF NOT EXISTS idx_mv_drp_drug
    ON mv_drug_reaction_pairs(drugname_clean);
CREATE INDEX IF NOT EXISTS idx_mv_drp_prodai
    ON mv_drug_reaction_pairs(prod_ai_clean);
CREATE INDEX IF NOT EXISTS idx_mv_drp_reaction
    ON mv_drug_reaction_pairs(reaction_term);
CREATE INDEX IF NOT EXISTS idx_mv_drp_quarter
    ON mv_drug_reaction_pairs(quarter);
CREATE INDEX IF NOT EXISTS idx_mv_drp_drug_trgm
    ON mv_drug_reaction_pairs USING gin(drugname_clean gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_drp_react_trgm
    ON mv_drug_reaction_pairs USING gin(reaction_term gin_trgm_ops);

-- VIEW 2: Drug Outcomes
-- "What patient outcomes are associated with drug X?"

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_drug_outcomes AS
SELECT
    d.drugname_clean,
    d.prod_ai_clean,
    d.role_cod,
    o.outc_cod,
    o.outcome_label,
    d.quarter,
    COUNT(DISTINCT d.report_id) AS report_count
FROM faers_drug d
JOIN faers_outc o ON d.report_id = o.report_id
JOIN mv_latest_cases lc ON d.report_id = lc.report_id
WHERE d.drugname_clean IS NOT NULL AND d.drugname_clean != ''
GROUP BY
    d.drugname_clean, d.prod_ai_clean, d.role_cod,
    o.outc_cod, o.outcome_label, d.quarter;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_do_unique
    ON mv_drug_outcomes(drugname_clean, prod_ai_clean, role_cod, outc_cod, outcome_label, quarter);
CREATE INDEX IF NOT EXISTS idx_mv_do_drug
    ON mv_drug_outcomes(drugname_clean);
CREATE INDEX IF NOT EXISTS idx_mv_do_drug_trgm
    ON mv_drug_outcomes USING gin(drugname_clean gin_trgm_ops);

-- VIEW 3: Death Reports by Drug (Critical Safety Signal)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_death_by_drug AS
SELECT
    d.drugname_clean,
    d.prod_ai_clean,
    d.quarter,
    COUNT(DISTINCT d.report_id)     AS death_reports,
    COUNT(DISTINCT d.report_id)::FLOAT /
        NULLIF((SELECT COUNT(DISTINCT d2.report_id) FROM faers_drug d2
                JOIN mv_latest_cases lc2 ON d2.report_id = lc2.report_id
                WHERE d2.role_cod = 'PS'), 0) * 100  AS pct_of_all_ps_reports
FROM faers_drug d
JOIN faers_outc o ON d.report_id = o.report_id
JOIN mv_latest_cases lc ON d.report_id = lc.report_id
WHERE o.outc_cod = 'DE'
  AND d.role_cod IN ('PS', 'SS')
  AND d.drugname_clean IS NOT NULL
  AND d.drugname_clean != ''
GROUP BY d.drugname_clean, d.prod_ai_clean, d.quarter;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_dbd_unique
    ON mv_death_by_drug(drugname_clean, quarter);
CREATE INDEX IF NOT EXISTS idx_mv_dbd_drug_trgm
    ON mv_death_by_drug USING gin(drugname_clean gin_trgm_ops);

-- VIEW 4: Reports by Country
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_reports_by_country AS
SELECT
    dem.reporter_country,
    dem.quarter,
    COUNT(DISTINCT dem.report_id)                                          AS report_count,
    COUNT(DISTINCT CASE WHEN o.outc_cod = 'DE' THEN dem.report_id END)    AS death_count,
    COUNT(DISTINCT CASE WHEN o.outc_cod = 'HO' THEN dem.report_id END)    AS hospitalization_count,
    COUNT(DISTINCT CASE WHEN o.outc_cod = 'LT' THEN dem.report_id END)    AS life_threatening_count
FROM faers_demo dem
JOIN mv_latest_cases lc ON dem.report_id = lc.report_id
LEFT JOIN faers_outc o ON dem.report_id = o.report_id
WHERE dem.reporter_country IS NOT NULL
GROUP BY dem.reporter_country, dem.quarter;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_rbc_unique
    ON mv_reports_by_country(reporter_country, quarter);

-- VIEW 5: PRR (Proportional Reporting Ratio) — Signal Detection
-- PRR = (a/b) / (c/d) where:
--   a = reports of drug + reaction
--   b = all reports of drug
--   c = reports of reaction (all drugs)
--   d = all reports
-- Signal threshold: PRR >= 2 AND N >= 3 (Evans criteria)

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_signal_prr AS
WITH
-- Total reports in database (all quarters combined)
totals AS (
    SELECT COUNT(DISTINCT dem.report_id) AS N FROM faers_demo dem
    JOIN mv_latest_cases lc ON dem.report_id = lc.report_id
),
-- Reports per drug (Primary Suspect only)
drug_totals AS (
    SELECT
        d.drugname_clean,
        d.quarter,
        COUNT(DISTINCT d.report_id) AS n_drug
    FROM faers_drug d
    JOIN mv_latest_cases lc ON d.report_id = lc.report_id
    WHERE d.role_cod = 'PS'
      AND d.drugname_clean IS NOT NULL AND d.drugname_clean != ''
    GROUP BY d.drugname_clean, d.quarter
),
-- Reports per reaction (all drugs)
reac_totals AS (
    SELECT
        r.pt_clean AS reaction_term,
        COUNT(DISTINCT r.report_id) AS n_reac
    FROM faers_reac r
    JOIN mv_latest_cases lc ON r.report_id = lc.report_id
    GROUP BY r.pt_clean
),
-- Drug-Reaction co-occurrence (Primary Suspect)
drug_reac_pairs AS (
    SELECT
        d.drugname_clean,
        r.pt_clean AS reaction_term,
        d.quarter,
        COUNT(DISTINCT d.report_id) AS a    -- reports with BOTH drug AND reaction
    FROM faers_drug d
    JOIN faers_reac r ON d.report_id = r.report_id
    JOIN mv_latest_cases lc ON d.report_id = lc.report_id
    WHERE d.role_cod = 'PS'
      AND d.drugname_clean IS NOT NULL AND d.drugname_clean != ''
    GROUP BY d.drugname_clean, r.pt_clean, d.quarter
)
SELECT
    drp.drugname_clean,
    drp.reaction_term,
    drp.quarter,
    drp.a                                       AS drug_reaction_count,
    dt.n_drug                                   AS drug_total,
    rt.n_reac                                   AS reaction_total,
    t.N                                         AS grand_total,
    -- PRR formula
    ROUND(
        (
            (drp.a::FLOAT / NULLIF(dt.n_drug, 0)) /
            NULLIF((rt.n_reac::FLOAT / NULLIF(t.N, 0)), 0)
        )::NUMERIC, 3)                               AS prr,
    -- ROR (Reporting Odds Ratio) — more robust at small N
    ROUND(
        (
            (drp.a::FLOAT * (t.N - rt.n_reac - dt.n_drug + drp.a)) /
            NULLIF(
                (dt.n_drug - drp.a)::FLOAT * (rt.n_reac - drp.a)
            , 0)
        )::NUMERIC, 3)                               AS ror,
    -- Signal flag
    CASE
        WHEN drp.a >= 3 AND
             (drp.a::FLOAT / NULLIF(dt.n_drug, 0)) /
             NULLIF((rt.n_reac::FLOAT / NULLIF(t.N, 0)), 0) >= 2
        THEN TRUE
        ELSE FALSE
    END                                         AS is_signal
FROM drug_reac_pairs drp
JOIN drug_totals dt ON drp.drugname_clean = dt.drugname_clean AND drp.quarter = dt.quarter
JOIN reac_totals rt ON drp.reaction_term = rt.reaction_term
CROSS JOIN totals t
WHERE drp.a >= 3     -- Minimum 3 reports to be considered
ORDER BY prr DESC NULLS LAST;

CREATE INDEX IF NOT EXISTS idx_mv_prr_drug
    ON mv_signal_prr(drugname_clean, quarter);
CREATE INDEX IF NOT EXISTS idx_mv_prr_signal
    ON mv_signal_prr(is_signal, prr DESC);
CREATE INDEX IF NOT EXISTS idx_mv_prr_drug_trgm
    ON mv_signal_prr USING gin(drugname_clean gin_trgm_ops);

-- VIEW 6: Age and Sex Distribution by Drug
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_age_sex_distribution AS
SELECT
    d.drugname_clean,
    d.quarter,
    dem.sex,
    dem.age_group,
    COUNT(DISTINCT d.report_id) AS report_count,
    AVG(dem.age_years)          AS avg_age,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY dem.age_years) AS median_age,
    AVG(dem.weight_kg)          AS avg_weight_kg
FROM faers_drug d
JOIN faers_demo dem ON d.report_id = dem.report_id
JOIN mv_latest_cases lc ON d.report_id = lc.report_id
WHERE d.role_cod = 'PS'
  AND d.drugname_clean IS NOT NULL AND d.drugname_clean != ''
GROUP BY d.drugname_clean, d.quarter, dem.sex, dem.age_group;

CREATE INDEX IF NOT EXISTS idx_mv_asd_drug
    ON mv_age_sex_distribution(drugname_clean, quarter);
CREATE INDEX IF NOT EXISTS idx_mv_asd_drug_trgm
    ON mv_age_sex_distribution USING gin(drugname_clean gin_trgm_ops);

-- VIEW 7: Quarterly Trends (time-series for dashboard)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_quarterly_trends AS
SELECT
    dem.quarter,
    COUNT(DISTINCT dem.report_id)                                       AS total_cases,
    COUNT(DISTINCT CASE WHEN o.outc_cod = 'DE' THEN dem.report_id END)  AS deaths,
    COUNT(DISTINCT CASE WHEN o.outc_cod = 'HO' THEN dem.report_id END)  AS hospitalizations,
    COUNT(DISTINCT CASE WHEN o.outc_cod = 'LT' THEN dem.report_id END)  AS life_threatening,
    COUNT(DISTINCT CASE WHEN dem.sex = 'Female' THEN dem.report_id END) AS female_cases,
    COUNT(DISTINCT CASE WHEN dem.sex = 'Male' THEN dem.report_id END)   AS male_cases,
    AVG(dem.age_years)                                                   AS avg_age,
    COUNT(DISTINCT dem.reporter_country)                                 AS reporting_countries
FROM faers_demo dem
JOIN mv_latest_cases lc ON dem.report_id = lc.report_id
LEFT JOIN faers_outc o ON dem.report_id = o.report_id
GROUP BY dem.quarter
ORDER BY dem.quarter;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_qt_quarter
    ON mv_quarterly_trends(quarter);

-- VIEW 8: Top Drugs Overall (quick lookup)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_top_drugs AS
SELECT
    drugname_clean,
    prod_ai_clean,
    quarter,
    COUNT(DISTINCT d.report_id) AS report_count,
    -- Breakdown by role
    COUNT(DISTINCT CASE WHEN d.role_cod = 'PS' THEN d.report_id END) AS ps_count,
    COUNT(DISTINCT CASE WHEN d.role_cod = 'SS' THEN d.report_id END) AS ss_count,
    COUNT(DISTINCT CASE WHEN d.role_cod = 'C'  THEN d.report_id END) AS concomitant_count
FROM faers_drug d
JOIN mv_latest_cases lc ON d.report_id = lc.report_id
WHERE d.drugname_clean IS NOT NULL AND d.drugname_clean != ''
GROUP BY d.drugname_clean, d.prod_ai_clean, d.quarter;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_td_unique
    ON mv_top_drugs(drugname_clean, prod_ai_clean, quarter);
CREATE INDEX IF NOT EXISTS idx_mv_td_drug_trgm
    ON mv_top_drugs USING gin(drugname_clean gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_td_count
    ON mv_top_drugs(report_count DESC);

-- VIEW 9: Top Reactions Overall
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_top_reactions AS
SELECT
    r.pt_clean AS reaction_term,
    r.quarter,
    COUNT(DISTINCT r.report_id) AS report_count
FROM faers_reac r
JOIN mv_latest_cases lc ON r.report_id = lc.report_id
WHERE r.pt_clean IS NOT NULL AND r.pt_clean != ''
GROUP BY r.pt_clean, r.quarter;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_tr_unique
    ON mv_top_reactions(reaction_term, quarter);
CREATE INDEX IF NOT EXISTS idx_mv_tr_trgm
    ON mv_top_reactions USING gin(reaction_term gin_trgm_ops);

-- Verify
DO $$
DECLARE v_count INT;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM pg_matviews
    WHERE schemaname = 'public';
    RAISE NOTICE '% materialized views created successfully.', v_count;
    RAISE NOTICE 'Refresh with: SELECT refresh_all_views();';
END $$;

-- Helper function to refresh all views
CREATE OR REPLACE FUNCTION refresh_all_views()
RETURNS void LANGUAGE plpgsql AS $$
DECLARE v TEXT;
BEGIN
    FOR v IN VALUES
        ('mv_latest_cases'),
        ('mv_drug_reaction_pairs'), ('mv_drug_outcomes'), ('mv_death_by_drug'),
        ('mv_reports_by_country'), ('mv_signal_prr'), ('mv_age_sex_distribution'),
        ('mv_quarterly_trends'), ('mv_top_drugs'), ('mv_top_reactions')
    LOOP
        EXECUTE 'REFRESH MATERIALIZED VIEW CONCURRENTLY ' || v;
        RAISE NOTICE 'Refreshed %', v;
    END LOOP;
END $$;
