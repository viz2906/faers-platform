# Disaster Recovery (DR) Plan — FAERS Analytics Platform

This document outlines the **Disaster Recovery (DR)** targets, backup schedule, step-by-step recovery procedures, and practice drill commands for the FAERS Analytics Platform.

---

## 1. Service Level Objectives (SLOs)

| Metric | Target | Description |
| :--- | :--- | :--- |
| **Recovery Time Objective (RTO)** | **1 Hour** | Maximum acceptable duration of service downtime during a disaster. |
| **Recovery Point Objective (RPO)** | **15 Minutes** | Maximum acceptable data loss duration (achieved via RDS Point-In-Time Recovery WAL logs). |

---

## 2. Backup Schedule & Strategy

| Backup Type | Frequency | Retention | Storage Location | Recovery Objective |
| :--- | :--- | :--- | :--- | :--- |
| **RDS Transaction Logs (WAL)** | Continuous (every 5 min) | 7 Days | Primary Region S3 (AWS Managed) | Point-In-Time Recovery (RPO ≤ 15 min) |
| **RDS Automated Snapshot** | Daily (03:00 UTC) | 7 Days | Primary Region AWS Backup | Full database snapshot recovery |
| **AWS Backup Cross-Region Copy** | Weekly (Sun 01:00 UTC) | 30 Days | Secondary DR Region Vault (`us-west-2`) | Regional disaster failover |
| **ECR Container Images** | Continuous (CI/CD push) | Last 20 tagged images | Primary & Secondary ECR | Immutable application artifact restore |

*Cross-region backup infrastructure is defined in [terraform/backup.tf](../terraform/backup.tf).*

---

## 3. Step-by-Step Disaster Recovery Procedure

In the event of database corruption, AZ failure, or primary region outage, follow these sequential steps to restore platform operations.

```
┌───────────────────────────┐    ┌───────────────────────────┐    ┌───────────────────────────┐    ┌───────────────────────────┐
│  Step 1: Restore RDS      │ ──►│  Step 2: Update Secrets   │ ──►│  Step 3: Redeploy ECS     │ ──►│  Step 4: Verify Health    │
│  (PITR or Snapshot)       │    │  (Secrets Manager Host)   │    │  (Force New Task / Tag)   │    │  (/livez & /health)       │
└───────────────────────────┘    └───────────────────────────┘    └───────────────────────────┘    └───────────────────────────┘
```

### Step 1: Restore RDS Database (Point-In-Time or Snapshot)

#### Option A: Point-In-Time Recovery (PITR — Preferred for RPO ≤ 15 min)
Restore the database to a specific timestamp right before the failure occurred:

```bash
# Restore RDS to a specific point-in-time (UTC)
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier faers-prod-postgres \
  --target-db-instance-identifier faers-prod-postgres-restored \
  --restore-time "2026-08-10T19:45:00Z" \
  --db-instance-class db.t3.micro \
  --db-subnet-group-name faers-prod-db-subnet-group \
  --vpc-security-group-ids sg-xxxxxxxxx \
  --no-multi-az \
  --region us-east-1

# Wait for restored database to become available
aws rds wait db-instance-available \
  --db-instance-identifier faers-prod-postgres-restored \
  --region us-east-1
```

#### Option B: Restore Latest Snapshot
Restore from the most recent daily snapshot:

```bash
# Find latest snapshot ARN
LATEST_SNAP=$(aws rds describe-db-snapshots \
  --db-instance-identifier faers-prod-postgres \
  --query "reverse(sort_by(DBSnapshots, &SnapshotCreateTime))[0].DBSnapshotArn" \
  --output text)

# Restore from snapshot
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier faers-prod-postgres-restored \
  --db-snapshot-identifier "${LATEST_SNAP}" \
  --db-instance-class db.t3.micro \
  --db-subnet-group-name faers-prod-db-subnet-group \
  --vpc-security-group-ids sg-xxxxxxxxx \
  --region us-east-1
```

---

### Step 2: Re-point DB Connection via Secrets Manager

Once the restored database status is `available`, extract its endpoint address and update the Secrets Manager JSON secret used by ECS tasks:

```bash
# Get restored database endpoint address
RESTORED_HOST=$(aws rds describe-db-instances \
  --db-instance-identifier faers-prod-postgres-restored \
  --query "DBInstances[0].Endpoint.Address" \
  --output text \
  --region us-east-1)

# Update Secrets Manager payload with the new host
aws secretsmanager update-secret \
  --secret-id "faers-prod/rds-credentials" \
  --secret-string "{\"host\":\"${RESTORED_HOST}\",\"port\":\"5432\",\"dbname\":\"faers\",\"username\":\"faers_user\",\"password\":\"YOUR_DB_PASSWORD\"}" \
  --region us-east-1
```

---

### Step 3: Redeploy ECS Services from Known-Good Image Tag

Force a new ECS deployment so tasks restart, fetch the updated database host secret from Secrets Manager, and establish connection to the restored database:

```bash
# 1. Force new deployment for API service
aws ecs update-service \
  --cluster faers-prod-cluster \
  --service faers-prod-api \
  --force-new-deployment \
  --region us-east-1

# 2. Force new deployment for Frontend service
aws ecs update-service \
  --cluster faers-prod-cluster \
  --service faers-prod-frontend \
  --force-new-deployment \
  --region us-east-1

# 3. Wait for service stability
aws ecs wait services-stable \
  --cluster faers-prod-cluster \
  --services faers-prod-api faers-prod-frontend \
  --region us-east-1
```

---

### Step 4: Verify Health & Data Integrity

Perform health checks against the platform endpoints:

```bash
# 1. Verify lightweight container liveness
curl -i https://faers.example.com/livez

# 2. Verify deep database and cache connectivity
curl -i https://faers.example.com/health

# 3. Run API query smoke test
curl -i -X POST https://faers.example.com/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the top 5 reported adverse events?"}'
```

---

## 4. Disaster Recovery Practice Drills

To test recovery procedures without disturbing production, use the provided drill script:

```bash
# Run a dry-run DR practice drill (restores latest snapshot into a scratch environment)
./scripts/dr-drill.sh

# When finished testing, tear down the scratch drill database
./scripts/dr-drill.sh --cleanup faers-dr-drill-<TIMESTAMP>
```
