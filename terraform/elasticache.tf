# ==============================================================================
# ElastiCache — Redis 7.2 (Replication Group, single node)
#
# Uses transit_encryption_enabled + an auth_token (stored in Secrets Manager)
# for in-transit security. The app must connect with ssl=True on port 6379.
#
# A replication_group is used (instead of aws_elasticache_cluster) because:
# 1. It is the only resource that supports Redis AUTH tokens.
# 2. It can be upgraded to multi-node/multi-AZ without resource recreation.
# ==============================================================================

resource "random_password" "redis_auth" {
  # Redis auth tokens: 16–128 printable ASCII chars, no spaces or @
  length           = 32
  special          = true
  override_special = "!&#$^<>-"   # Subset that Redis accepts in auth tokens
}

# ---- Secrets Manager — Redis Credentials -------------------------------------

resource "aws_secretsmanager_secret" "redis" {
  name        = "${local.name_prefix}/redis-credentials"
  description = "ElastiCache Redis auth token and connection details for the FAERS platform."

  recovery_window_in_days = 7

  tags = {
    Name      = "${local.name_prefix}-redis-secret"
    Component = "cache"
  }
}

resource "aws_secretsmanager_secret_version" "redis" {
  secret_id = aws_secretsmanager_secret.redis.id

  secret_string = jsonencode({
    # Note: connect with TLS (ssl=True in redis-py) because transit_encryption_enabled = true
    host       = aws_elasticache_replication_group.main.primary_endpoint_address
    port       = "6379"
    auth_token = random_password.redis_auth.result
  })
}

# ---- ElastiCache Subnet Group ------------------------------------------------

resource "aws_elasticache_subnet_group" "main" {
  name        = "${local.name_prefix}-cache-subnet-group"
  description = "Private DB subnets for FAERS ElastiCache Redis."
  subnet_ids  = aws_subnet.db_private[*].id

  tags = {
    Name = "${local.name_prefix}-cache-subnet-group"
  }
}

# ---- Redis Parameter Group ---------------------------------------------------

resource "aws_elasticache_parameter_group" "main" {
  name   = "${local.name_prefix}-redis7"
  family = "redis7"

  # Evict least-recently-used keys when maxmemory is reached (matches docker-compose config)
  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }

  tags = {
    Name = "${local.name_prefix}-redis7-params"
  }
}

# ---- ElastiCache Replication Group (single-node Redis) -----------------------

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${local.name_prefix}-redis"
  description          = "FAERS Redis query-result cache."

  engine         = "redis"
  engine_version = "7.2"
  node_type      = var.elasticache_node_type

  # Single node — no failover. Set num_cache_clusters >= 2 and
  # automatic_failover_enabled = true for HA.
  num_cache_clusters         = 1
  automatic_failover_enabled = false
  multi_az_enabled           = false

  port                   = 6379
  subnet_group_name      = aws_elasticache_subnet_group.main.name
  security_group_ids     = [aws_security_group.db.id]
  parameter_group_name   = aws_elasticache_parameter_group.main.name

  # Security: in-transit TLS + AUTH token (required pair)
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth.result
  at_rest_encryption_enabled = true

  # Maintenance and snapshots
  maintenance_window       = "sun:05:00-sun:06:00"
  snapshot_retention_limit = 1    # Keep 1 daily snapshot for free tier
  snapshot_window          = "02:00-03:00"

  apply_immediately = true   # Apply parameter changes without waiting for maintenance window

  tags = {
    Name      = "${local.name_prefix}-redis"
    Component = "cache"
  }
}
