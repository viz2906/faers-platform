# ==============================================================================
# Outputs — useful IDs for downstream Terraform modules (ECS, RDS, etc.)
# ==============================================================================

output "vpc_id" {
  description = "ID of the FAERS VPC."
  value       = aws_vpc.main.id
}

output "vpc_cidr" {
  description = "CIDR block of the FAERS VPC."
  value       = aws_vpc.main.cidr_block
}

# ---- Subnet IDs --------------------------------------------------------------

output "public_subnet_ids" {
  description = "IDs of the 2 public subnets (ALB, NAT gateway)."
  value       = aws_subnet.public[*].id
}

output "ecs_private_subnet_ids" {
  description = "IDs of the 2 private ECS subnets (ECS tasks)."
  value       = aws_subnet.ecs_private[*].id
}

output "db_private_subnet_ids" {
  description = "IDs of the 2 private DB subnets (RDS, ElastiCache)."
  value       = aws_subnet.db_private[*].id
}

# ---- Gateway IDs -------------------------------------------------------------

output "internet_gateway_id" {
  description = "ID of the Internet Gateway."
  value       = aws_internet_gateway.main.id
}

output "nat_gateway_ids" {
  description = "IDs of the per-AZ NAT Gateways."
  value       = aws_nat_gateway.main[*].id
}

output "nat_gateway_public_ips" {
  description = "Public (Elastic) IP addresses of the NAT Gateways. Whitelist these in external API providers."
  value       = aws_eip.nat[*].public_ip
}

# ---- Security Group IDs ------------------------------------------------------

output "alb_sg_id" {
  description = "Security group ID for the Application Load Balancer."
  value       = aws_security_group.alb.id
}

output "ecs_sg_id" {
  description = "Security group ID for ECS tasks."
  value       = aws_security_group.ecs.id
}

output "db_sg_id" {
  description = "Security group ID for RDS / ElastiCache (DB tier)."
  value       = aws_security_group.db.id
}

# ==============================================================================
# ALB
# ==============================================================================

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer. Point your domain's CNAME (or Alias record) here."
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "Route 53 Hosted Zone ID of the ALB. Use for Alias records in Route 53."
  value       = aws_lb.main.zone_id
}

output "alb_arn" {
  description = "ARN of the Application Load Balancer."
  value       = aws_lb.main.arn
}

# ==============================================================================
# ECR
# ==============================================================================

output "api_ecr_repo_url" {
  description = "ECR repository URL for the FastAPI image. Use as the base for docker push and ECS task image references."
  value       = aws_ecr_repository.api.repository_url
}

output "frontend_ecr_repo_url" {
  description = "ECR repository URL for the Next.js frontend image."
  value       = aws_ecr_repository.frontend.repository_url
}

# ==============================================================================
# ECS
# ==============================================================================

output "ecs_cluster_name" {
  description = "Name of the ECS Fargate cluster."
  value       = aws_ecs_cluster.main.name
}

output "ecs_cluster_arn" {
  description = "ARN of the ECS Fargate cluster."
  value       = aws_ecs_cluster.main.arn
}

# ==============================================================================
# RDS
# ==============================================================================

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint hostname (without port). Also stored in the db secret."
  value       = aws_db_instance.main.address
  sensitive   = true
}

output "rds_port" {
  description = "RDS PostgreSQL port."
  value       = aws_db_instance.main.port
}

output "db_secret_arn" {
  description = "ARN of the Secrets Manager secret containing RDS credentials (host, port, dbname, username, password)."
  value       = aws_secretsmanager_secret.db.arn
}

# ==============================================================================
# ElastiCache
# ==============================================================================

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint hostname. Connect with TLS (ssl=True) and the auth_token from the redis secret."
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
  sensitive   = true
}

output "redis_secret_arn" {
  description = "ARN of the Secrets Manager secret containing Redis connection details (host, port, auth_token)."
  value       = aws_secretsmanager_secret.redis.arn
}

# ==============================================================================
# Convenience — copy-paste docker push commands
# ==============================================================================

output "ecr_push_commands" {
  description = "Commands to authenticate and push images to ECR. Replace <TAG> with your image tag."
  value = <<-EOT
    # Authenticate Docker to ECR:
    aws ecr get-login-password --region ${var.aws_region} | \
      docker login --username AWS --password-stdin ${aws_ecr_repository.api.repository_url}

    # Push API image:
    docker tag faers-api:prod ${aws_ecr_repository.api.repository_url}:<TAG>
    docker push            ${aws_ecr_repository.api.repository_url}:<TAG>

    # Push Frontend image:
    docker tag faers-frontend:prod ${aws_ecr_repository.frontend.repository_url}:<TAG>
    docker push                ${aws_ecr_repository.frontend.repository_url}:<TAG>
  EOT
}

# ==============================================================================
# GitHub OIDC
# ==============================================================================

output "github_actions_role_arn" {
  description = "ARN of the IAM role assumed by GitHub Actions via OIDC. Set AWS_ACCOUNT_ID in GitHub Secrets and construct role ARN dynamically in the workflow."
  value       = aws_iam_role.github_actions_deploy.arn
}

output "github_oidc_provider_arn" {
  description = "ARN of the GitHub OIDC identity provider. Only one should exist per AWS account."
  value       = aws_iam_openid_connect_provider.github.arn
}


