#!/usr/bin/env bash
# ==============================================================================
# FAERS Analytics Platform — Disaster Recovery Drill Script
# ==============================================================================
# Usage:
#   ./scripts/dr-drill.sh [--cleanup scratch-db-identifier]
#
# Description:
#   Automates spinning up a restored RDS PostgreSQL instance from the latest
#   automated/manual snapshot into a temporary scratch environment.
#   This allows the engineering team to practice DR recovery procedures without
#   impacting the production database or services.
# ==============================================================================

set -euo pipefail

# Configuration defaults
AWS_REGION="${AWS_REGION:-us-east-1}"
PROD_DB_IDENTIFIER="${PROD_DB_IDENTIFIER:-faers-prod-postgres}"
SCRATCH_PREFIX="${SCRATCH_PREFIX:-faers-dr-drill}"
TIMESTAMP=$(date +"%Y%m%d%H%M%S")
SCRATCH_DB_IDENTIFIER="${SCRATCH_PREFIX}-${TIMESTAMP}"
DB_SUBNET_GROUP="${DB_SUBNET_GROUP:-faers-prod-db-subnet-group}"
DB_SECURITY_GROUP="${DB_SECURITY_GROUP:-}"

echo "======================================================================"
echo " FAERS Disaster Recovery Practice Drill"
echo " Region:               ${AWS_REGION}"
echo " Source DB Identifier: ${PROD_DB_IDENTIFIER}"
echo " Scratch DB Target:    ${SCRATCH_DB_IDENTIFIER}"
echo "======================================================================"

# Cleanup mode handle
if [[ "${1:-}" == "--cleanup" ]]; then
    CLEANUP_TARGET="${2:-}"
    if [[ -z "${CLEANUP_TARGET}" ]]; then
        echo "Error: Must specify scratch DB identifier to clean up."
        echo "Usage: ./scripts/dr-drill.sh --cleanup <scratch-db-identifier>"
        exit 1
    fi
    echo "Cleaning up DR drill instance: ${CLEANUP_TARGET}..."
    aws rds delete-db-instance \
        --db-instance-identifier "${CLEANUP_TARGET}" \
        --skip-final-snapshot \
        --delete-automated-backups \
        --region "${AWS_REGION}"
    echo "Deletion initiated for ${CLEANUP_TARGET}. Cleanup complete!"
    exit 0
fi

# Step 1: Find latest available snapshot
echo "[Step 1/4] Searching for latest snapshot of '${PROD_DB_IDENTIFIER}'..."
LATEST_SNAPSHOT_ARN=$(aws rds describe-db-snapshots \
    --db-instance-identifier "${PROD_DB_IDENTIFIER}" \
    --query "reverse(sort_by(DBSnapshots, &SnapshotCreateTime))[0].DBSnapshotArn" \
    --output text \
    --region "${AWS_REGION}")

if [[ -z "${LATEST_SNAPSHOT_ARN}" || "${LATEST_SNAPSHOT_ARN}" == "None" ]]; then
    echo "Error: No snapshot found for DB instance '${PROD_DB_IDENTIFIER}'."
    exit 1
fi

echo "  Found snapshot: ${LATEST_SNAPSHOT_ARN}"

# Step 2: Restore snapshot into scratch DB instance
echo "[Step 2/4] Restoring snapshot to scratch DB '${SCRATCH_DB_IDENTIFIER}'..."
aws rds restore-db-instance-from-db-snapshot \
    --db-instance-identifier "${SCRATCH_DB_IDENTIFIER}" \
    --db-snapshot-identifier "${LATEST_SNAPSHOT_ARN}" \
    --db-instance-class db.t3.micro \
    --no-multi-az \
    --publicly-accessible \
    --no-deletion-protection \
    --region "${AWS_REGION}" \
    > /dev/null

echo "  Restore request submitted successfully."

# Step 3: Wait for restored instance to become available
echo "[Step 3/4] Waiting for restored DB to reach 'available' state (may take 5–10 minutes)..."
aws rds wait db-instance-available \
    --db-instance-identifier "${SCRATCH_DB_IDENTIFIER}" \
    --region "${AWS_REGION}"

# Step 4: Output connection information
RESTORED_ENDPOINT=$(aws rds describe-db-instances \
    --db-instance-identifier "${SCRATCH_DB_IDENTIFIER}" \
    --query "DBInstances[0].Endpoint.Address" \
    --output text \
    --region "${AWS_REGION}")

RESTORED_PORT=$(aws rds describe-db-instances \
    --db-instance-identifier "${SCRATCH_DB_IDENTIFIER}" \
    --query "DBInstances[0].Endpoint.Port" \
    --output text \
    --region "${AWS_REGION}")

echo "======================================================================"
echo " DR Drill Setup Complete!"
echo " Restored DB Endpoint: ${RESTORED_ENDPOINT}"
echo " Restored DB Port:     ${RESTORED_PORT}"
echo ""
echo " You can test connecting to this scratch database using psql:"
echo "   psql -h ${RESTORED_ENDPOINT} -p ${RESTORED_PORT} -U faers_user -d faers"
echo ""
echo " When done practicing, clean up the scratch instance by running:"
echo "   ./scripts/dr-drill.sh --cleanup ${SCRATCH_DB_IDENTIFIER}"
echo "======================================================================"
