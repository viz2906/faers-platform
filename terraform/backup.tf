# ==============================================================================
# AWS Backup — Cross-Region Automated RDS Backup
#
# Primary Vault:   In primary region (var.aws_region)
# Secondary Vault: In DR region (var.dr_aws_region)
# Plan:            Weekly backup rule copying snapshots to DR region for regional DR.
# Target:          RDS PostgreSQL instance (aws_db_instance.main)
# ==============================================================================

# ---- IAM Role — AWS Backup Service Role --------------------------------------

resource "aws_iam_role" "aws_backup" {
  name        = "${local.name_prefix}-aws-backup-role"
  description = "Service role assumed by AWS Backup to create and copy snapshots across regions."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "backup.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${local.name_prefix}-aws-backup-role"
  }
}

resource "aws_iam_role_policy_attachment" "aws_backup_service" {
  role       = aws_iam_role.aws_backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_iam_role_policy_attachment" "aws_backup_restore" {
  role       = aws_iam_role.aws_backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores"
}

# ---- Backup Vaults -----------------------------------------------------------

# Primary region vault
resource "aws_backup_vault" "primary" {
  name        = "${local.name_prefix}-backup-vault-primary"
  kms_key_arn = null   # Uses default AWS-managed KMS key for AWS Backup

  tags = {
    Name = "${local.name_prefix}-backup-vault-primary"
  }
}

# Secondary region vault (DR region)
resource "aws_backup_vault" "dr" {
  provider    = aws.dr
  name        = "${local.name_prefix}-backup-vault-dr"
  kms_key_arn = null

  tags = {
    Name = "${local.name_prefix}-backup-vault-dr"
  }
}

# ---- Backup Plan -------------------------------------------------------------

resource "aws_backup_plan" "rds_dr" {
  name = "${local.name_prefix}-rds-weekly-dr-plan"

  # Weekly rule: Every Sunday at 01:00 UTC, copy snapshot to DR region
  rule {
    rule_name         = "weekly-cross-region-copy"
    target_vault_name = aws_backup_vault.primary.name
    schedule          = "cron(0 1 ? * SUN *)"   # Every Sunday at 01:00 UTC

    lifecycle {
      delete_after = 30   # Retain weekly snapshots for 30 days
    }

    # Cross-region copy action to DR region vault
    copy_action {
      destination_vault_arn = aws_backup_vault.dr.arn

      lifecycle {
        delete_after = 30   # Retain copy in DR region for 30 days
      }
    }
  }

  tags = {
    Name = "${local.name_prefix}-rds-weekly-dr-plan"
  }
}

# ---- Backup Selection --------------------------------------------------------

resource "aws_backup_selection" "rds" {
  name         = "${local.name_prefix}-rds-backup-selection"
  iam_role_arn = aws_iam_role.aws_backup.arn
  plan_id      = aws_backup_plan.rds_dr.id

  resources = [
    aws_db_instance.main.arn,
  ]
}
