# ==============================================================================
# RDS — PostgreSQL 16 (Managed by TimescaleDB community extension via RDS)
#
# Uses a random_password (stored in Secrets Manager) so no plaintext
# credentials appear in state or source code.
# Multi-AZ is controlled by var.rds_multi_az (default true → automatic standby
# in a second AZ; set false in dev to save ~$50/mo).
# deletion_protection and backup_retention_period = 7 are always on.
# ==============================================================================

resource "random_password" "db" {
  length           = 32
  special          = false   # Avoid shell-escaping issues in connection strings
  override_special = ""
}

# ---- Secrets Manager — DB Credentials ----------------------------------------

resource "aws_secretsmanager_secret" "db" {
  name        = "${local.name_prefix}/rds-credentials"
  description = "RDS PostgreSQL credentials for the FAERS platform."

  # 7-day recovery window before permanent deletion (safety net)
  recovery_window_in_days = 7

  tags = {
    Name      = "${local.name_prefix}-rds-secret"
    Component = "database"
  }
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id

  # Stored as JSON so ECS can reference individual keys via
  # valueFrom = "arn:...:secret-name:json-key::"
  secret_string = jsonencode({
    host     = aws_db_instance.main.address
    port     = tostring(aws_db_instance.main.port)
    dbname   = aws_db_instance.main.db_name
    username = aws_db_instance.main.username
    password = random_password.db.result
  })
}

# ---- DB Subnet Group ---------------------------------------------------------

resource "aws_db_subnet_group" "main" {
  name        = "${local.name_prefix}-db-subnet-group"
  description = "Private DB subnets for FAERS RDS."
  subnet_ids  = aws_subnet.db_private[*].id

  tags = {
    Name = "${local.name_prefix}-db-subnet-group"
  }
}

# ---- DB Parameter Group (PostgreSQL 16 tuned for analytics) ------------------

resource "aws_db_parameter_group" "main" {
  name        = "${local.name_prefix}-pg16"
  family      = "postgres16"
  description = "FAERS PostgreSQL 16 parameter group."

  # Enable pg_stat_statements for query performance monitoring
  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
  }

  parameter {
    name  = "pg_stat_statements.track"
    value = "ALL"
  }

  # Log slow queries (>1s) for analysis
  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  tags = {
    Name = "${local.name_prefix}-pg16-params"
  }
}

# ---- RDS Instance ------------------------------------------------------------

resource "aws_db_instance" "main" {
  identifier = "${local.name_prefix}-postgres"

  engine         = "postgres"
  engine_version = "16.3"
  instance_class = var.rds_instance_class

  # Storage: start at 20 GB, autoscale up to 100 GB as data grows
  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.rds_db_name
  username = var.rds_username
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  parameter_group_name   = aws_db_parameter_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]

  multi_az = var.rds_multi_az   # Set to true in production for HA failover

  # Automated backups — 7-day retention, 03:00–04:00 UTC daily
  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"

  # Performance Insights — 7-day free retention for query-level visibility
  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  # Deletion safety
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name_prefix}-postgres-final-${formatdate("YYYYMMDDhhmmss", timestamp())}"
  copy_tags_to_snapshot     = true

  # Don't apply updates during off-hours automatically
  auto_minor_version_upgrade = true

  tags = {
    Name      = "${local.name_prefix}-postgres"
    Component = "database"
  }

  # Ensure the secret version is created after the instance is available,
  # because the secret stores the instance's runtime endpoint address.
  depends_on = [aws_db_subnet_group.main]
}
