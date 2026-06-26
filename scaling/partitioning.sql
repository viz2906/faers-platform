-- ============================================================
-- Declarative Partitioning by Quarter (Scaling Step 1)
-- ============================================================
-- Apply BEFORE loading data for best performance.
-- Or migrate existing tables using pg_partman.
-- ============================================================

-- DEMO table partitioned by quarter list
CREATE TABLE IF NOT EXISTS faers_demo_partitioned (
    primaryid           BIGINT      NOT NULL,
    caseid              BIGINT      NOT NULL,
    caseversion         INT,
    quarter             VARCHAR(10) NOT NULL,
    i_f_code            CHAR(1),
    event_dt            DATE,
    fda_dt              DATE,
    rept_cod            VARCHAR(10),
    age_years           DOUBLE PRECISION,
    sex                 VARCHAR(10),
    weight_kg           DOUBLE PRECISION,
    age_group           VARCHAR(50),
    reporter_country    VARCHAR(5),
    occr_country        VARCHAR(5),
    occp_cod            VARCHAR(5),
    PRIMARY KEY (primaryid, quarter)
) PARTITION BY LIST (quarter);

-- Create partitions for each quarter (add new one each quarter)
-- Template:
DO $$
DECLARE
    quarters TEXT[] := ARRAY[
        '2026q1', '2025q4', '2025q3', '2025q2', '2025q1',
        '2024q4', '2024q3', '2024q2', '2024q1',
        '2023q4', '2023q3', '2023q2', '2023q1',
        '2022q4', '2022q3', '2022q2', '2022q1'
    ];
    q TEXT;
BEGIN
    FOREACH q IN ARRAY quarters LOOP
        BEGIN
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS faers_demo_%s
                 PARTITION OF faers_demo_partitioned
                 FOR VALUES IN (''%s'')',
                replace(q, 'q', '_q'), q
            );
            RAISE NOTICE 'Created partition for %', q;
        EXCEPTION WHEN duplicate_table THEN
            -- Partition already exists, skip
            NULL;
        END;
    END LOOP;
END $$;

-- ============================================================
-- QUERY PRUNING EXAMPLE
-- ============================================================
-- This query only scans the 2026q1 partition:
--   SELECT * FROM faers_demo_partitioned WHERE quarter = '2026q1';
--
-- This scans 4 partitions (2025, all quarters):
--   SELECT * FROM faers_demo_partitioned
--   WHERE quarter IN ('2025q1','2025q2','2025q3','2025q4');
--
-- Without partitioning: would scan ALL rows
-- With partitioning: skips 95%+ of data for single-quarter queries

-- ============================================================
-- Adding new quarter (run each quarter when new data arrives)
-- ============================================================
-- CREATE TABLE faers_demo_2026_q2
-- PARTITION OF faers_demo_partitioned
-- FOR VALUES IN ('2026q2');

-- ============================================================
-- Partition inspection
-- ============================================================
SELECT
    parent.relname AS parent_table,
    child.relname AS partition_name,
    pg_get_expr(child.relpartbound, child.oid) AS partition_values,
    pg_size_pretty(pg_relation_size(child.oid)) AS partition_size
FROM pg_inherits
JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
JOIN pg_class child  ON pg_inherits.inhrelid  = child.oid
WHERE parent.relname = 'faers_demo_partitioned'
ORDER BY child.relname;
