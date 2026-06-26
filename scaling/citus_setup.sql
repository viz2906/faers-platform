-- ============================================================
-- Citus Distributed PostgreSQL Setup for FAERS at Infinite Scale
-- ============================================================
-- When to use: After 50+ quarters (~500M+ total rows), or when
-- single PostgreSQL node can't serve concurrent query load.
-- ============================================================
-- 
-- STEP 1: Install Citus extension (on all nodes)
-- See: https://docs.citusdata.com/en/stable/installation/multi_node_rhel.html
--
-- STEP 2: Create coordinator and workers
-- On coordinator: SELECT citus_set_coordinator_host('coordinator.host', 5432);
-- Add workers: SELECT citus_add_node('worker1.host', 5432);
--              SELECT citus_add_node('worker2.host', 5432);
--              SELECT citus_add_node('worker3.host', 5432);
-- ============================================================

-- Create the extension on the coordinator
CREATE EXTENSION IF NOT EXISTS citus;

-- ============================================================
-- DISTRIBUTION STRATEGY
-- ============================================================
--
-- Key: distribute by primaryid (natural distribution key)
-- Reason: All tables JOIN on primaryid → co-location means
--         JOINs happen locally within each shard = no network hop
--
-- Distribution type: HASH (balanced distribution)
-- Shard count: 32 (default, good for up to ~12 nodes)

-- Distribute DEMO first (it's the "reference" table for FKs)
SELECT create_distributed_table('faers_demo', 'primaryid',
    shard_count => 32);

-- Co-locate all child tables with DEMO on primaryid
-- This ensures JOIN on primaryid = local shard join (fast!)
SELECT create_distributed_table('faers_drug', 'primaryid',
    colocate_with => 'faers_demo');

SELECT create_distributed_table('faers_reac', 'primaryid',
    colocate_with => 'faers_demo');

SELECT create_distributed_table('faers_outc', 'primaryid',
    colocate_with => 'faers_demo');

SELECT create_distributed_table('faers_ther', 'primaryid',
    colocate_with => 'faers_demo');

SELECT create_distributed_table('faers_indi', 'primaryid',
    colocate_with => 'faers_demo');

SELECT create_distributed_table('faers_rpsr', 'primaryid',
    colocate_with => 'faers_demo');

-- NLQ log can stay as reference table (small, needs to be on all nodes)
SELECT create_reference_table('nlq_query_log');
SELECT create_reference_table('faers_quarter_metadata');
SELECT create_reference_table('drug_name_mappings');

-- ============================================================
-- Verify distribution
-- ============================================================
SELECT table_name, citus_table_type, colocation_id, distribution_column
FROM citus_tables
ORDER BY table_name;

-- ============================================================
-- Shard rebalancing (run after adding new worker nodes)
-- ============================================================
-- SELECT rebalance_table_shards('faers_demo');

-- ============================================================
-- Scaling commands
-- ============================================================

-- Add a new worker (zero-downtime)
-- SELECT citus_add_node('worker4.host', 5432);
-- SELECT rebalance_table_shards();  -- Rebalance shards to new node

-- Check shard placement
-- SELECT * FROM citus_shards LIMIT 20;

-- Monitor distributed query performance
-- SELECT * FROM citus_stat_statements ORDER BY total_exec_time DESC LIMIT 10;

-- ============================================================
-- DISTRIBUTED MATERIALIZED VIEWS
-- ============================================================
-- Note: Citus doesn't natively support materialized views across shards.
-- Strategy: Keep materialized views on the coordinator only,
-- populated from distributed query results.

-- Coordinator-only view (aggregates from all shards)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_drug_reaction_pairs AS
SELECT
    d.drugname_clean,
    d.prod_ai_clean,
    d.role_cod,
    r.pt_clean AS reaction_term,
    d.quarter,
    COUNT(DISTINCT d.primaryid) AS report_count
FROM faers_drug d
JOIN faers_reac r ON d.primaryid = r.primaryid  -- LOCAL join (co-located!)
WHERE d.drugname_clean IS NOT NULL AND d.drugname_clean != ''
  AND r.pt_clean IS NOT NULL
GROUP BY d.drugname_clean, d.prod_ai_clean, d.role_cod, r.pt_clean, d.quarter;

-- Index the coordinator view
CREATE INDEX IF NOT EXISTS idx_mv_citus_drp_drug
    ON mv_drug_reaction_pairs(drugname_clean);
CREATE INDEX IF NOT EXISTS idx_mv_citus_drp_drug_trgm
    ON mv_drug_reaction_pairs USING gin(drugname_clean gin_trgm_ops);

-- ============================================================
-- PERFORMANCE MONITORING on Citus
-- ============================================================

-- Check which workers are being used
-- SELECT * FROM citus_worker_stat_activity;

-- Explain distributed query plan
-- EXPLAIN SELECT COUNT(*) FROM faers_drug WHERE drugname_clean ILIKE '%ASPIRIN%';
-- Look for "Custom Scan (Citus Adaptive)" — means it's using distributed execution

-- ============================================================
-- CITUS HORIZONTAL SCALING MATH
-- ============================================================
--
-- 1 node  × 32 shards = handles ~200M rows, ~100 concurrent queries
-- 3 nodes × 32 shards = handles ~600M rows, ~300 concurrent queries
-- 6 nodes × 32 shards = handles ~1.2B rows, ~600 concurrent queries
-- 12 nodes × 32 shards = handles ~2.4B rows, ~1200 concurrent queries
--
-- Each node: 16 vCPUs, 64 GB RAM, 2 TB NVMe SSD (e.g., AWS r6i.4xlarge)
-- Cost: ~$800/month per node on AWS
--
-- For FAERS specifically:
-- All historical data (2004-2026) ≈ 500M rows total
-- → 3 Citus nodes is more than enough for ALL historical FAERS data
--
-- ============================================================
