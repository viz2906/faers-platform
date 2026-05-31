# FDA FAERS Analytics Platform

## 🚀 Quick Start (4 commands)

```bash
# 1. Copy and fill environment variables
cp .env.example .env
# Edit .env: add OPENAI_API_KEY, confirm DB settings

# 2. Start PostgreSQL + Redis
docker-compose up -d postgres redis

# 3. Download and load one quarter of FAERS data (~5-10 minutes)
pip install -r requirements.txt
python ingestion/quarterly_pipeline.py --quarter 2026q1

# 4. Start the API
uvicorn api.main:app --reload
# → API docs at http://localhost:8000/docs

# 5. Start the frontend (new terminal)
cd frontend && npm install && npm run dev
# → Dashboard at http://localhost:3000
```

---

## 📊 What This Does

Transforms raw FDA FAERS adverse event data into a queryable analytics platform:

| Feature | Description |
|---------|-------------|
| **Data Ingestion** | Download → Parse → Clean → Load 7 FAERS tables |
| **Analytics Engine** | 9 pre-built materialized views for <100ms responses |
| **NLP Query Engine** | Ask questions in plain English → auto-generates SQL → explains results |
| **Signal Detection** | PRR + ROR disproportionality analysis per FDA/Evans criteria |
| **REST API** | 12 analytics endpoints + NL query endpoint |
| **Dashboard** | Drug rankings, trends, country map, outcome breakdown |
| **Infinite Scaling** | PostgreSQL partitions → DuckDB/Parquet → Citus |

---

## 🗂️ Project Structure

```
faers_platform/
├── ingestion/              # Data pipeline
│   ├── parse_faers.py      # ASCII parser (handles latin-1, $-delimiter, bad dates)
│   ├── load_to_db.py       # PostgreSQL COPY bulk loader
│   └── quarterly_pipeline.py  # Full orchestration
├── database/
│   ├── schema.sql          # All tables + indexes (including GIN trigram)
│   └── materialized_views.sql  # 9 pre-built analytics views
├── nlp/
│   ├── system_prompt.py    # LLM schema context + few-shot examples
│   ├── query_engine.py     # NL → SQL → Execute → Explain
│   └── sql_validator.py    # Security guardrails
├── api/
│   ├── main.py             # FastAPI app
│   └── routes/
│       ├── analytics.py    # 12 pre-built endpoints
│       └── nlp.py          # NL query endpoint
├── analytics/
│   └── duckdb_engine.py    # Columnar analytics (PRR, cross-quarter)
├── scaling/
│   ├── parquet_export.py   # PostgreSQL → Parquet files
│   ├── citus_setup.sql     # Distributed PostgreSQL
│   └── partitioning.sql    # List partitioning by quarter
└── frontend/               # Next.js dashboard
```

---

## 🔌 Key API Endpoints

```
GET  /health                                   → System health
GET  /api/v1/analytics/summary                 → DB overview stats
GET  /api/v1/analytics/top-drugs               → Top drugs by reports
GET  /api/v1/analytics/drug/{name}/reactions   → Drug → reactions
GET  /api/v1/analytics/drug/{name}/outcomes    → Drug → patient outcomes
GET  /api/v1/analytics/drug/{name}/signal      → PRR/ROR signal detection
GET  /api/v1/analytics/drug/{name}/demographics → Age/sex breakdown
GET  /api/v1/analytics/deaths/top-drugs        → Death-associated drugs
GET  /api/v1/analytics/countries               → Geographic distribution
GET  /api/v1/analytics/trends                  → Quarterly time series
POST /api/v1/nlp/query                         → Natural language → SQL
GET  /api/v1/nlp/examples                      → Example questions
```

---

## 🧠 NLP Query Examples

```bash
# Natural language → SQL in <5 seconds
curl -X POST http://localhost:8000/api/v1/nlp/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the top adverse reactions for warfarin?"}'
```

Questions you can ask:
- *"What are the top 20 adverse reactions for aspirin?"*
- *"Which drugs have the most death reports in 2026 Q1?"*
- *"Show me the safety signals for metformin"*
- *"What is the age distribution of patients reporting reactions to ozempic?"*
- *"Compare deaths between aspirin and ibuprofen"*
- *"Which countries report the most adverse events?"*

---

## 📈 Scaling Decision Tree

```
                 How many quarters do you have?
                         │
              ┌──────────┴──────────┐
              ≤ 10 quarters          > 10 quarters
              │                     │
   Single PostgreSQL +        Add DuckDB Parquet
   partitions + views         layer for analytics
   ✓ Works great              │
   ✓ < 5s response            > 50 quarters (all history)?
                              │
                    ┌─────────┴──────────┐
                    Citus (distributed)  S3 + DuckDB
                    Same SQL interface   Cheapest option
                    Linear scaling       Best for pure analytics
```

**Rule of thumb:** Start simple. One well-tuned PostgreSQL instance with:
- `shared_buffers = 25% RAM`
- `effective_cache_size = 75% RAM`
- Materialized views refreshed nightly
- Redis caching hot queries

...handles all 50+ historical FAERS quarters (~500M rows) comfortably.

---

## 📐 Data Schema Quick Reference

| Table | Rows/Quarter | Key Fields |
|-------|-------------|------------|
| `faers_demo` | ~600K | primaryid, age_years, sex, reporter_country, event_dt |
| `faers_drug` | ~3M | primaryid, drug_seq, role_cod (PS/SS/C/I), drugname_clean |
| `faers_reac` | ~2M | primaryid, pt_clean (MedDRA term) |
| `faers_outc` | ~1M | primaryid, outc_cod (DE/LT/HO/DS/CA/RI/OT) |
| `faers_ther` | ~2M | primaryid, drug_seq, start_dt, end_dt, dur_days |
| `faers_indi` | ~2M | primaryid, drug_seq, indi_pt_clean |
| `faers_rpsr` | ~600K | primaryid, rpsr_cod |

**Join key:** Always join on `primaryid`
**Drug search:** Use `ILIKE '%drug%'` on `drugname_clean` (GIN trigram index)
**Signal detection:** PRR ≥ 2 AND N ≥ 3 = Evans criteria for signal

---

## ⚠️ FAERS Data Interpretation

FAERS is a **spontaneous reporting system**, not a clinical trial:

1. **Not causation** — high counts mean reporting interest, not proven drug effects
2. **Reporting bias** — serious events over-reported; mild events under-reported
3. **Duplicate reports** — same event can be reported by patient AND manufacturer
4. **Incomplete data** — many fields are optional and missing
5. **Confounding** — patients often take multiple drugs simultaneously

Always complement FAERS findings with clinical literature and pharmacoepidemiological methods.
