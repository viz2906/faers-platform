# ==============================================================================
# FAERS Platform — Network Layer
#
# Resources defined here:
#   VPC
#   ├── 2 × public  subnets  (ALB, NAT gateway)
#   ├── 2 × private subnets  (ECS tasks — egress via NAT)
#   └── 2 × private subnets  (RDS / ElastiCache — no internet egress)
#   Internet Gateway
#   NAT Gateway (single, in public-subnet-0 — cost-optimised)
#   Route tables:
#     public_rt   → IGW  (associated with public subnets)
#     ecs_rt      → NAT  (associated with ECS private subnets)
#     db_rt       → local only (associated with DB private subnets)
#   Security groups:
#     alb_sg  — allows HTTPS (443) + HTTP (80) from 0.0.0.0/0
#     ecs_sg  — allows traffic only from alb_sg
#     db_sg   — allows 5432 (PostgreSQL) and 6379 (Redis) only from ecs_sg
# ==============================================================================

locals {
  # Build fully-qualified AZ names from suffix list, e.g. "us-east-1a"
  azs = [for suffix in var.availability_zones : "${var.aws_region}${suffix}"]
  name_prefix = "${var.project}-${var.environment}"
}

# ==============================================================================
# VPC
# ==============================================================================

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true   # Required for RDS endpoint resolution

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

# ==============================================================================
# Public Subnets  (ALB + NAT gateway)
# ==============================================================================

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true   # Instances launched here get a public IP

  tags = {
    Name = "${local.name_prefix}-public-${local.azs[count.index]}"
    Tier = "public"
  }
}

# ==============================================================================
# Private ECS Subnets  (ECS tasks — outbound via NAT, no inbound from internet)
# ==============================================================================

resource "aws_subnet" "ecs_private" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.ecs_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name_prefix}-ecs-private-${local.azs[count.index]}"
    Tier = "ecs-private"
  }
}

# ==============================================================================
# Private DB Subnets  (RDS / ElastiCache — fully isolated, no internet egress)
# ==============================================================================

resource "aws_subnet" "db_private" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.db_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name_prefix}-db-private-${local.azs[count.index]}"
    Tier = "db-private"
  }
}

# ==============================================================================
# Internet Gateway
# ==============================================================================

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

# ==============================================================================
# NAT Gateway  (single — cost-optimised; accepts slightly longer failover time)
#
# Placed in public-subnet[0]. If you need HA, add a second EIP + NAT in [1]
# and a separate private route table pointing to it; adjust var.nat_az_index.
# ==============================================================================

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "${local.name_prefix}-nat-eip"
  }

  # EIP must exist after the IGW is attached; Terraform needs this hint
  depends_on = [aws_internet_gateway.main]
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id   # Placed in the first public subnet

  tags = {
    Name = "${local.name_prefix}-nat"
  }

  depends_on = [aws_internet_gateway.main]
}

# ==============================================================================
# Route Tables
# ==============================================================================

# ---- Public route table — default route via Internet Gateway ----------------

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${local.name_prefix}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ---- ECS private route table — egress via single NAT gateway ----------------

resource "aws_route_table" "ecs_private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = {
    Name = "${local.name_prefix}-ecs-private-rt"
  }
}

resource "aws_route_table_association" "ecs_private" {
  count          = 2
  subnet_id      = aws_subnet.ecs_private[count.index].id
  route_table_id = aws_route_table.ecs_private.id
}

# ---- DB private route table — local only, intentionally no internet egress --
# RDS and ElastiCache never need to initiate outbound connections.

resource "aws_route_table" "db_private" {
  vpc_id = aws_vpc.main.id

  # No explicit routes added — the implicit "local" route (VPC CIDR) is
  # automatically present and sufficient for DB instances.

  tags = {
    Name = "${local.name_prefix}-db-private-rt"
  }
}

resource "aws_route_table_association" "db_private" {
  count          = 2
  subnet_id      = aws_subnet.db_private[count.index].id
  route_table_id = aws_route_table.db_private.id
}

# ==============================================================================
# Security Groups
# ==============================================================================

# ---- ALB Security Group — internet-facing -----------------------------------
# Accepts HTTPS (443) from anywhere and HTTP (80) so that load balancers can
# respond to ACME HTTP-01 challenges or redirect to HTTPS.

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb-sg"
  description = "Allow HTTPS/HTTP inbound from internet; all egress to VPC."
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP from internet (ACME challenge / redirect)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Allow all egress — ALB needs to forward to ECS tasks on dynamic ports
  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-alb-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ---- ECS Security Group — private, ALB-sourced traffic only -----------------
# ECS tasks accept traffic only from the ALB security group. Application ports
# (8000 for FastAPI, 3000 for Next.js) are referenced by ECS task definitions.

resource "aws_security_group" "ecs" {
  name        = "${local.name_prefix}-ecs-sg"
  description = "Allow inbound from ALB only; allow all egress (NAT for pip/npm)."
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "All TCP from ALB security group"
    from_port       = 0
    to_port         = 65535
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "All egress (outbound via NAT for image pulls, API calls)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-ecs-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ---- DB Security Group — ECS-sourced traffic only ---------------------------
# Allows PostgreSQL (5432) and Redis (6379) only from the ECS security group.
# All other inbound traffic — including from the ALB — is denied.

resource "aws_security_group" "db" {
  name        = "${local.name_prefix}-db-sg"
  description = "Allow PostgreSQL (5432) and Redis (6379) from ECS SG only."
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from ECS tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  ingress {
    description     = "Redis from ECS tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  # DB instances initiate no outbound connections; deny all egress explicitly.
  egress {
    description = "No outbound internet access for DB tier"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["127.0.0.1/32"]   # Effectively blocks all egress
  }

  tags = {
    Name = "${local.name_prefix}-db-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}
