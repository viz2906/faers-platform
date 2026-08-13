# terraform/terraform.tfvars
# ─────────────────────────────────────────────────────────────────────────────
# Real deployment values — gitignored, do NOT commit.
# Based on terraform.tfvars.example; edit values for your AWS account.
# ─────────────────────────────────────────────────────────────────────────────

# ==============================================================================
# General
# ==============================================================================

aws_region  = "us-east-1"
environment = "prod"
project     = "faers"

# ==============================================================================
# Network
# ==============================================================================

vpc_cidr            = "10.0.0.0/16"
availability_zones  = ["a", "b"]
public_subnet_cidrs = ["10.0.0.0/24", "10.0.1.0/24"]
ecs_subnet_cidrs    = ["10.0.10.0/24", "10.0.11.0/24"]
db_subnet_cidrs     = ["10.0.20.0/24", "10.0.21.0/24"]

# ==============================================================================
# DNS / TLS
# ==============================================================================

# HTTP-only for now; flip to true once a domain is delegated to Route 53.
# See terraform/README.md → "Enabling HTTPS" for the step-by-step procedure.
enable_https = false

# Required only when enable_https = true.  Leave commented out until ready.
# domain_name     = "faers.example.com"
# route53_zone_id = "Z0123456789ABCDEFGHIJ"

# ==============================================================================
# ECR
# ==============================================================================

ecr_max_image_count = 20

# ==============================================================================
# ECS — Compute sizing
# ==============================================================================

ecs_desired_count   = 2
ecs_api_cpu         = 512
ecs_api_memory      = 1024
ecs_frontend_cpu    = 256
ecs_frontend_memory = 512

# ECS image tags — overridden by CI on each deploy (e.g. --var="api_image_tag=sha-abc1234")
api_image_tag      = "latest"
frontend_image_tag = "latest"

# ==============================================================================
# ECS — Auto Scaling
# ==============================================================================

ecs_min_capacity                = 2
ecs_max_capacity                = 6
autoscaling_cpu_target          = 60
autoscaling_alb_target_requests = 1000

# ==============================================================================
# RDS — PostgreSQL
# ==============================================================================

rds_instance_class = "db.t3.small" # Upgraded from micro for prod analytics workload
rds_db_name        = "faers"
rds_username       = "faers_user"
rds_multi_az       = true # HA standby in a second AZ; set false in dev to save ~$50/mo

# ==============================================================================
# ElastiCache — Redis
# ==============================================================================

elasticache_node_type = "cache.t3.micro"

# ==============================================================================
# Observability
# ==============================================================================

log_retention_days = 30

# ==============================================================================
# GitHub OIDC — required (no default)
# Format: "owner/repo", e.g. "viz2906/faers-platform"
# ==============================================================================

github_repo = "viz2906/faers-platform"

# OpenAI / Gemini API Key for Natural Language Querying (NLQ)
openai_api_key = ""   # Set via AWS Secrets Manager or GitHub Actions secret — never commit here

