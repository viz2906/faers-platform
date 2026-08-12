# ==============================================================================
# ECS — Fargate Cluster, IAM Roles, Task Definitions, Services
#
# Architecture:
#   ECS Cluster (Container Insights enabled)
#   ├── API Service  — 2 Fargate tasks in private ECS subnets
#   │     registers to alb: aws_lb_target_group.api
#   └── Frontend Service — 2 Fargate tasks in private ECS subnets
#         registers to alb: aws_lb_target_group.frontend
#
# Both services read secrets from AWS Secrets Manager at task launch.
# CloudWatch log groups are created for structured container logging.
# ==============================================================================

# ---- ECS Cluster -------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled" # Enables CloudWatch Container Insights metrics
  }

  tags = {
    Name = "${local.name_prefix}-cluster"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1 # Guarantee at least 1 task on FARGATE (not SPOT)
  }
}

# ---- CloudWatch Log Groups ---------------------------------------------------

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name_prefix}/api"
  retention_in_days = var.log_retention_days

  tags = {
    Name      = "${local.name_prefix}-api-logs"
    Component = "api"
  }
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${local.name_prefix}/frontend"
  retention_in_days = var.log_retention_days

  tags = {
    Name      = "${local.name_prefix}-frontend-logs"
    Component = "frontend"
  }
}

# ==============================================================================
# IAM — ECS Task Execution Role
#
# Used by the ECS agent (not the app container) to:
# - Pull images from ECR
# - Write logs to CloudWatch
# - Read secrets from Secrets Manager at task launch
# ==============================================================================

resource "aws_iam_role" "ecs_task_execution" {
  name = "${local.name_prefix}-ecs-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${local.name_prefix}-ecs-task-execution"
  }
}

# AWS-managed policy: ECR pull + CloudWatch Logs write
resource "aws_iam_role_policy_attachment" "ecs_task_execution_managed" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Inline policy: allow reading the RDS and Redis secrets at container startup
resource "aws_iam_role_policy" "ecs_task_execution_secrets" {
  name = "${local.name_prefix}-secrets-read"
  role = aws_iam_role.ecs_task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ReadFAERSSecrets"
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
      ]
      Resource = [
        aws_secretsmanager_secret.db.arn,
        aws_secretsmanager_secret.redis.arn,
      ]
    }]
  })
}

# ==============================================================================
# IAM — ECS Task Role (assumed by the application container itself)
#
# Add AWS SDK permissions here if the app needs to call other AWS services
# (e.g., S3 for Parquet data, SQS, Bedrock, etc.).
# ==============================================================================

resource "aws_iam_role" "ecs_task" {
  name = "${local.name_prefix}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${local.name_prefix}-ecs-task"
  }
}

# ==============================================================================
# ECS Task Definition — API (FastAPI)
# ==============================================================================

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc" # Required for Fargate
  cpu                      = var.ecs_api_cpu
  memory                   = var.ecs_api_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
      essential = true

      portMappings = [{
        containerPort = 8000
        protocol      = "tcp"
      }]

      # Non-sensitive configuration as plain environment variables
      environment = [
        { name = "API_HOST", value = "0.0.0.0" },
        { name = "API_PORT", value = "8000" },
        { name = "API_WORKERS", value = "4" },
        { name = "POSTGRES_PORT", value = "5432" },
        { name = "REDIS_PORT", value = "6379" },
        { name = "REDIS_DB", value = "0" },
        { name = "REDIS_TTL_SECONDS", value = "3600" },
        { name = "ENABLE_CACHE", value = "true" },
        { name = "EXPLAIN_RESULTS", value = "true" },
        { name = "QUERY_TIMEOUT_SECONDS", value = "5" },
        # ElastiCache uses TLS — the redis-py client must be configured with ssl=True
        { name = "REDIS_SSL", value = "true" },
      ]

      # Sensitive values — pulled from Secrets Manager by the ECS agent at launch.
      # Format: "arn:...:secret-name:json-key::" extracts a single JSON field.
      secrets = [
        {
          name      = "POSTGRES_HOST"
          valueFrom = "${aws_secretsmanager_secret.db.arn}:host::"
        },
        {
          name      = "POSTGRES_DB"
          valueFrom = "${aws_secretsmanager_secret.db.arn}:dbname::"
        },
        {
          name      = "POSTGRES_USER"
          valueFrom = "${aws_secretsmanager_secret.db.arn}:username::"
        },
        {
          name      = "POSTGRES_PASSWORD"
          valueFrom = "${aws_secretsmanager_secret.db.arn}:password::"
        },
        {
          name      = "REDIS_HOST"
          valueFrom = "${aws_secretsmanager_secret.redis.arn}:host::"
        },
        {
          name      = "REDIS_PASSWORD" # Used as the AUTH token by redis-py
          valueFrom = "${aws_secretsmanager_secret.redis.arn}:auth_token::"
        },
      ]

      # Container-level health check (complements ALB health check)
      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/livez || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 15
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }

      # Let the container use up to its full task memory allocation
      memoryReservation = floor(var.ecs_api_memory * 0.75)
    }
  ])

  tags = {
    Name      = "${local.name_prefix}-api-task"
    Component = "api"
  }

  depends_on = [
    aws_secretsmanager_secret_version.db,
    aws_secretsmanager_secret_version.redis,
  ]
}

# ==============================================================================
# ECS Task Definition — Frontend (Next.js standalone)
# ==============================================================================

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.name_prefix}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_frontend_cpu
  memory                   = var.ecs_frontend_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "frontend"
      image     = "${aws_ecr_repository.frontend.repository_url}:${var.frontend_image_tag}"
      essential = true

      portMappings = [{
        containerPort = 3000
        protocol      = "tcp"
      }]

      environment = [
        { name = "NODE_ENV", value = "production" },
        { name = "PORT", value = "3000" },
        { name = "HOSTNAME", value = "0.0.0.0" },
        # NEXT_PUBLIC_API_URL must point to the ALB public domain — browsers call this.
        # The value is baked into the JS bundle at Docker build time (--build-arg).
        # This env var here is informational; it does NOT override the baked value.
        { name = "NEXT_PUBLIC_API_URL", value = "https://${var.domain_name}/api/v1" },
      ]

      healthCheck = {
        command     = ["CMD-SHELL", "wget -qO- http://localhost:3000/api/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "frontend"
        }
      }

      memoryReservation = floor(var.ecs_frontend_memory * 0.75)
    }
  ])

  tags = {
    Name      = "${local.name_prefix}-frontend-task"
    Component = "frontend"
  }
}

# ==============================================================================
# ECS Services
# ==============================================================================

resource "aws_ecs_service" "api" {
  name            = "${local.name_prefix}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.ecs_desired_count

  # CODE_DEPLOY controller: Terraform provisions the service; all subsequent
  # task definition updates and traffic shifts are owned by CodeDeploy.
  # deployment_minimum_healthy_percent / maximum_percent are ignored by
  # CODE_DEPLOY — CodeDeploy manages the green task count independently.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }

  network_configuration {
    subnets          = aws_subnet.ecs_private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  # Initial registration: blue target group.
  # CodeDeploy swaps between blue and green on each deployment.
  # lifecycle.ignore_changes below prevents Terraform reverting this after
  # CodeDeploy has taken ownership.
  load_balancer {
    target_group_arn = aws_lb_target_group.api_blue.arn
    container_name   = "api"
    container_port   = 8000
  }

  # deployment_circuit_breaker is incompatible with CODE_DEPLOY controller.
  # Rollback is handled by CodeDeploy alarms defined in codedeploy.tf.

  deployment_controller {
    type = "CODE_DEPLOY"
  }

  depends_on = [
    aws_lb_listener_rule.api,
    aws_iam_role_policy_attachment.ecs_task_execution_managed,
    aws_iam_role_policy.ecs_task_execution_secrets,
  ]

  tags = {
    Name      = "${local.name_prefix}-api-service"
    Component = "api"
  }

  lifecycle {
    ignore_changes = [
      # CodeDeploy owns the active task definition revision after first deploy
      task_definition,
      # CodeDeploy swaps the load_balancer target group between blue and green
      load_balancer,
      # Allow autoscaler to adjust without Terraform fighting it
      desired_count,
    ]
  }
}

resource "aws_ecs_service" "frontend" {
  name            = "${local.name_prefix}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = var.ecs_desired_count

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }

  network_configuration {
    subnets          = aws_subnet.ecs_private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend_blue.arn
    container_name   = "frontend"
    container_port   = 3000
  }

  deployment_controller {
    type = "CODE_DEPLOY"
  }

  depends_on = [
    aws_lb_listener.https,
    aws_iam_role_policy_attachment.ecs_task_execution_managed,
  ]

  tags = {
    Name      = "${local.name_prefix}-frontend-service"
    Component = "frontend"
  }

  lifecycle {
    ignore_changes = [
      task_definition,
      load_balancer,
      desired_count,
    ]
  }
}
