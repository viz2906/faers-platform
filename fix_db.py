import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('POSTGRES_HOST', 'localhost'),
    port=int(os.getenv('POSTGRES_PORT', 5432)),
    database=os.getenv('POSTGRES_DB', 'faers'),
    user=os.getenv('POSTGRES_USER', 'faers_user'),
    password=os.getenv('POSTGRES_PASSWORD', 'faers_secret_pw'),
)
conn.autocommit = True
cur = conn.cursor()

views = [
    'mv_drug_reaction_pairs', 'mv_drug_outcomes', 'mv_death_by_drug',
    'mv_reports_by_country', 'mv_signal_prr', 'mv_age_sex_distribution',
    'mv_quarterly_trends', 'mv_top_drugs', 'mv_top_reactions'
]

for v in views:
    cur.execute(f"DROP MATERIALIZED VIEW IF EXISTS {v} CASCADE;")

cur.execute("ALTER TABLE faers_demo ALTER COLUMN reporter_country TYPE VARCHAR(100);")
cur.execute("ALTER TABLE faers_demo ALTER COLUMN occr_country TYPE VARCHAR(100);")

with open('database/materialized_views.sql') as f:
    sql = f.read()
    cur.execute(sql)

print("Schema updated successfully!")
