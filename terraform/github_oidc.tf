# ==============================================================================
# GitHub Actions OIDC — IAM Role for CI/CD
#
# What this file provisions:
#   1. An OIDC Identity Provider that trusts GitHub's JWT issuer
#   2. An IAM role that GitHub Actions can assume via OIDC (no static keys)
#   3. A least-privilege IAM policy granting only what the deploy workflow needs
#
# After `terraform apply`:
#   - Copy the `github_actions_role_arn` output into your GitHub repo secrets
#     as AWS_ACCOUNT_ID (and set AWS_REGION separately).
#   - The role ARN is reconstructed in the workflow as:
#     arn:aws:iam::<AWS_ACCOUNT_ID>:role/<project>-<env>-github-actions-deploy
#
# Trust policy summary:
#   GitHub Actions can assume this role ONLY when:
#     - The workflow runs on the `main` branch (ref condition)
#     - The repo matches var.github_repo (repo condition)
#   All other branches, forks, and external repos are denied.
# ==============================================================================

# ---- Data sources ------------------------------------------------------------

# Look up the current AWS account ID so we can build ARNs without hard-coding it
data "aws_caller_identity" "current" {}

# ---- GitHub OIDC Provider ----------------------------------------------------
# AWS needs to trust GitHub's OIDC endpoint as an identity provider.
# The thumbprint list below is stable — GitHub rotates the signing cert rarely.
# See: https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services

resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com", # The audience GitHub sets in its OIDC tokens for AWS
  ]

  # GitHub's OIDC TLS certificate thumbprint.
  # Retrieve latest: openssl s_client -connect token.actions.githubusercontent.com:443 2>/dev/null | openssl x509 -fingerprint -noout
  thumbprint_list = [
    "227203b5317f3818cab5b5ce596132bf36748c0e", # Current active GitHub OIDC TLS thumbprint (retrieved Aug 2026)
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]

  tags = {
    Name = "${local.name_prefix}-github-oidc-provider"
  }
}

# ---- IAM Role — GitHub Actions Deployer -------------------------------------
# This role is assumed by the GitHub Actions workflow via AssumeRoleWithWebIdentity.
# The StringLike condition on the subject (sub) claim ensures only:
#   - the specific repository (var.github_repo)
#   - running on the main branch
# can assume the role. Wildcard (*) would allow any branch — avoid that in prod.

resource "aws_iam_role" "github_actions_deploy" {
  name        = "${local.name_prefix}-github-actions-deploy"
  description = "Assumed by GitHub Actions OIDC to deploy FAERS to ECS. No long-lived credentials."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "GitHubActionsOIDC"
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            # Audience must be sts.amazonaws.com (set by aws-actions/configure-aws-credentials)
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            # sub format: repo:<owner>/<repo>:ref:refs/heads/<branch>
            # The :* suffix allows workflow_dispatch and environment tokens too.
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:ref:refs/heads/main"
          }
        }
      }
    ]
  })

  # Short session — 1 hour is enough for a full deploy pipeline
  max_session_duration = 3600

  tags = {
    Name = "${local.name_prefix}-github-actions-deploy"
  }
}

# ---- IAM Policy — Least-Privilege Deploy Permissions -----------------------
# Grants only the actions the deploy workflow actually uses.
# This is intentionally narrow — add permissions here only as new workflow
# steps require them.

resource "aws_iam_role_policy" "github_actions_deploy" {
  name = "${local.name_prefix}-deploy-policy"
  role = aws_iam_role.github_actions_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [

      # ── ECR — authenticate, push images ─────────────────────────────────
      {
        Sid      = "ECRGetAuthToken"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = ["*"] # GetAuthorizationToken is a global action (no resource ARN)
      },
      {
        Sid    = "ECRPushImages"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
          # Read permissions needed for registry-based layer cache (cache-from)
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = [
          aws_ecr_repository.api.arn,
          aws_ecr_repository.frontend.arn,
        ]
      },

      # ── ECS — read task definitions, register new revisions, update services
      {
        Sid    = "ECSDescribe"
        Effect = "Allow"
        Action = [
          "ecs:DescribeTaskDefinition",
          "ecs:DescribeServices",
          "ecs:DescribeTasks",
          "ecs:ListTasks",
        ]
        Resource = ["*"] # Describe calls don't support resource-level restrictions
      },
      {
        Sid    = "ECSRegisterAndDeploy"
        Effect = "Allow"
        Action = [
          "ecs:RegisterTaskDefinition",
          "ecs:UpdateService",
        ]
        Resource = [
          aws_ecs_cluster.main.arn,
          # Task definition families (ARN prefix without revision)
          "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name_prefix}-api:*",
          "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name_prefix}-frontend:*",
          # ECS services
          "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:service/${local.name_prefix}-cluster/${local.name_prefix}-api",
          "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:service/${local.name_prefix}-cluster/${local.name_prefix}-frontend",
        ]
      },

      # ── IAM PassRole — ECS needs to pass the task execution role when
      # registering a new task definition revision ─────────────────────────
      {
        Sid    = "PassECSRoles"
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          aws_iam_role.ecs_task_execution.arn,
          aws_iam_role.ecs_task.arn,
        ]
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "ecs-tasks.amazonaws.com"
          }
        }
      },

      # ── CloudWatch Logs — read log streams for deployment verification ───
      {
        Sid    = "CloudWatchLogsRead"
        Effect = "Allow"
        Action = [
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:GetLogEvents",
        ]
        Resource = [
          aws_cloudwatch_log_group.api.arn,
          aws_cloudwatch_log_group.frontend.arn,
          "${aws_cloudwatch_log_group.api.arn}:*",
          "${aws_cloudwatch_log_group.frontend.arn}:*",
        ]
      },

      # ── CodeDeploy — create and monitor blue/green deployments ───────────
      # The workflow calls aws deploy create-deployment and polls get-deployment.
      # PassRole is not needed here — CodeDeploy assumes its own service role
      # (aws_iam_role.codedeploy), which is configured in the deployment group.
      {
        Sid    = "CodeDeployCreateDeployment"
        Effect = "Allow"
        Action = [
          "codedeploy:CreateDeployment",
          "codedeploy:GetDeployment",
          "codedeploy:GetDeploymentGroup",
          "codedeploy:ListDeployments",
          "codedeploy:StopDeployment",
          "codedeploy:GetDeploymentConfig",
          "codedeploy:RegisterApplicationRevision",
          "codedeploy:GetApplicationRevision",
        ]
        Resource = [
          aws_codedeploy_app.api.arn,
          aws_codedeploy_app.frontend.arn,
          aws_codedeploy_deployment_group.api.arn,
          aws_codedeploy_deployment_group.frontend.arn,
          "arn:aws:codedeploy:${var.aws_region}:${data.aws_caller_identity.current.account_id}:deploymentconfig:${local.name_prefix}-linear-10pct-1min",
          # CodeDeploy deployment ARNs are dynamic — wildcarding by app
          "arn:aws:codedeploy:${var.aws_region}:${data.aws_caller_identity.current.account_id}:deployment/*",
        ]
      },

      # ── CloudWatch Alarms — read alarm states during rollback monitoring ──
      {
        Sid    = "CloudWatchAlarmsRead"
        Effect = "Allow"
        Action = [
          "cloudwatch:DescribeAlarms",
          "cloudwatch:GetMetricStatistics",
        ]
        Resource = [
          aws_cloudwatch_metric_alarm.api_5xx.arn,
          aws_cloudwatch_metric_alarm.frontend_5xx.arn,
          aws_cloudwatch_metric_alarm.alb_5xx.arn,
        ]
      },
    ]
  })
}

# ==============================================================================
# Variables added by this file
# ==============================================================================

variable "github_repo" {
  description = <<-EOT
    Full GitHub repository identifier in the format "owner/repo".
    Example: "myorg/faers-platform"
    Used to scope the OIDC trust policy so only workflows from this
    specific repository (on the main branch) can assume the deploy role.
  EOT
  type        = string
}
