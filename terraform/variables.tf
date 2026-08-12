# ==============================================================================
# General
# ==============================================================================

variable "aws_region" {
  description = "AWS region to deploy all resources into."
  type        = string
  default     = "us-east-1"
}

variable "dr_aws_region" {
  description = "Secondary AWS region for Disaster Recovery backups and cross-region replication."
  type        = string
  default     = "us-west-2"
}


variable "environment" {
  description = "Deployment environment label (dev | staging | prod). Applied as a tag to every resource."
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "project" {
  description = "Short project identifier. Used as a prefix in resource names."
  type        = string
  default     = "faers"
}

# ==============================================================================
# Network — CIDR blocks
# ==============================================================================

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of exactly 2 AZ suffixes to use (e.g. [\"a\", \"b\"]). Combined with aws_region."
  type        = list(string)
  default     = ["a", "b"]

  validation {
    condition     = length(var.availability_zones) == 2
    error_message = "Exactly 2 availability zones must be specified."
  }
}

# Public subnets — host the ALB and NAT gateway. Must have routes to the IGW.
variable "public_subnet_cidrs" {
  description = "CIDR blocks for the 2 public subnets (one per AZ). Must be subsets of vpc_cidr."
  type        = list(string)
  default     = ["10.0.0.0/24", "10.0.1.0/24"]

  validation {
    condition     = length(var.public_subnet_cidrs) == 2
    error_message = "Exactly 2 public subnet CIDRs must be provided."
  }
}

# Private ECS subnets — ECS tasks run here, egress via the single NAT gateway.
variable "ecs_subnet_cidrs" {
  description = "CIDR blocks for the 2 private ECS subnets (one per AZ). Must be subsets of vpc_cidr."
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24"]

  validation {
    condition     = length(var.ecs_subnet_cidrs) == 2
    error_message = "Exactly 2 ECS subnet CIDRs must be provided."
  }
}

# Private DB subnets — RDS (PostgreSQL) and ElastiCache (Redis) only.
# No internet egress; completely isolated from public traffic.
variable "db_subnet_cidrs" {
  description = "CIDR blocks for the 2 private DB subnets (one per AZ). Must be subsets of vpc_cidr."
  type        = list(string)
  default     = ["10.0.20.0/24", "10.0.21.0/24"]

  validation {
    condition     = length(var.db_subnet_cidrs) == 2
    error_message = "Exactly 2 DB subnet CIDRs must be provided."
  }
}

# ==============================================================================
# DNS / TLS
# ==============================================================================

variable "enable_https" {
  description = <<-EOT
    When true:  provision an ACM certificate, an HTTPS (443) listener, and an
                HTTP (80) → HTTPS redirect.  Requires domain_name and route53_zone_id.
    When false: create only an HTTP (80) listener forwarding to the target groups.
                No domain or certificate is needed; use the ALB DNS name directly.
  EOT
  type        = bool
  default     = false
}

variable "domain_name" {
  description = "Public domain name for the platform (e.g. faers.example.com). Required when enable_https = true."
  type        = string
  default     = "" # Optional — only used when enable_https = true

  validation {
    condition     = !var.enable_https || (var.domain_name != null && var.domain_name != "")
    error_message = "domain_name must be set when enable_https = true."
  }
}

variable "route53_zone_id" {
  description = "Route 53 hosted zone ID for var.domain_name. Required when enable_https = true."
  type        = string
  default     = "" # Optional — only used when enable_https = true

  validation {
    condition     = !var.enable_https || (var.route53_zone_id != null && var.route53_zone_id != "")
    error_message = "route53_zone_id must be set when enable_https = true."
  }
}

# ==============================================================================
# ECR
# ==============================================================================

variable "ecr_max_image_count" {
  description = "Maximum number of tagged images to retain in each ECR repository. Older images are expired by the lifecycle policy."
  type        = number
  default     = 20
}

# ==============================================================================
# ECS — Compute sizing
# ==============================================================================

variable "ecs_desired_count" {
  description = "Desired number of running tasks for each ECS service."
  type        = number
  default     = 2
}

variable "ecs_api_cpu" {
  description = "CPU units for the API Fargate task (1024 = 1 vCPU). Valid Fargate combinations: 256/512/1024/2048/4096."
  type        = number
  default     = 512
}

variable "ecs_api_memory" {
  description = "Memory (MiB) for the API Fargate task. Must be a valid value for the chosen CPU."
  type        = number
  default     = 1024
}

variable "ecs_frontend_cpu" {
  description = "CPU units for the Next.js Fargate task."
  type        = number
  default     = 256
}

variable "ecs_frontend_memory" {
  description = "Memory (MiB) for the Next.js Fargate task."
  type        = number
  default     = 512
}

# ==============================================================================
# ECS — Image tags (updated by CI/CD on each deploy)
# ==============================================================================

variable "api_image_tag" {
  description = "Docker image tag to deploy for the FastAPI service. Typically a git SHA or semver tag set by CI."
  type        = string
  default     = "latest"
}

variable "frontend_image_tag" {
  description = "Docker image tag to deploy for the Next.js frontend service."
  type        = string
  default     = "latest"
}

# ==============================================================================
# RDS
# ==============================================================================

variable "rds_instance_class" {
  description = "RDS instance class for PostgreSQL. db.t3.small is the production default (db.t3.micro is too small for concurrent analytics queries)."
  type        = string
  default     = "db.t3.small"
}

variable "rds_db_name" {
  description = "Name of the PostgreSQL database to create inside the RDS instance."
  type        = string
  default     = "faers"
}

variable "rds_username" {
  description = "Master username for the RDS PostgreSQL instance."
  type        = string
  default     = "faers_user"
}

variable "rds_multi_az" {
  description = "Enable RDS Multi-AZ for automatic failover. Doubles the instance cost; recommended (and defaulted) for production."
  type        = bool
  default     = true
}

# ==============================================================================
# ElastiCache
# ==============================================================================

variable "elasticache_node_type" {
  description = "ElastiCache node type for the Redis replication group."
  type        = string
  default     = "cache.t3.micro"
}

# ==============================================================================
# Observability
# ==============================================================================

variable "log_retention_days" {
  description = "Number of days to retain ECS container logs in CloudWatch. Set to 0 for indefinite retention."
  type        = number
  default     = 30
}

# ==============================================================================
# Auto Scaling
# ==============================================================================

variable "ecs_min_capacity" {
  description = "Minimum number of ECS tasks to maintain for Auto Scaling."
  type        = number
  default     = 2
}

variable "ecs_max_capacity" {
  description = "Maximum number of ECS tasks allowed for Auto Scaling during high load."
  type        = number
  default     = 6
}

variable "autoscaling_cpu_target" {
  description = "Target average CPU utilization percentage for ECS task Auto Scaling."
  type        = number
  default     = 60
}

variable "autoscaling_alb_target_requests" {
  description = "Target ALB request count per target for API service Auto Scaling."
  type        = number
  default     = 1000
}


