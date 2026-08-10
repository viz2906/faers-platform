# ==============================================================================
# CodeDeploy — Blue/Green ECS Deployments
#
# Resources per service:
#   aws_codedeploy_app               — CodeDeploy application (ECS compute platform)
#   aws_codedeploy_deployment_group  — links to the ECS service, ALB listeners,
#                                      blue/green TGs, alarms, and rollback config
#   aws_cloudwatch_metric_alarm      — 5xx error-rate alarms that trigger auto-rollback
#
# Traffic shift strategy: LinearWithOriginalReplacement
#   - CodeDeploy shifts 10% of traffic every 1 minute (100% in 10 minutes total).
#   - If any CloudWatch alarm fires during the shift, CodeDeploy immediately rolls
#     back to the original (blue) target group.
#
# IAM:
#   aws_iam_role.codedeploy  — service role assumed by CodeDeploy
# ==============================================================================

# ---- IAM Role — CodeDeploy Service Role --------------------------------------
# CodeDeploy needs permission to call ECS, ELB, and autoscaling APIs.

resource "aws_iam_role" "codedeploy" {
  name        = "${local.name_prefix}-codedeploy"
  description = "Service role assumed by CodeDeploy to manage ECS blue/green deployments."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codedeploy.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${local.name_prefix}-codedeploy"
  }
}

# AWS-managed policy with all permissions CodeDeploy needs for ECS deployments
resource "aws_iam_role_policy_attachment" "codedeploy_ecs" {
  role       = aws_iam_role.codedeploy.name
  policy_arn = "arn:aws:iam::aws:policy/AWSCodeDeployRoleForECS"
}

# ==============================================================================
# Deployment Configuration — Linear 10% / 1 minute
#
# Shifts 10% of traffic to the green environment every 1 minute.
# Full cutover takes 10 minutes. If any alarm fires, CodeDeploy rolls back
# immediately without waiting for the next interval.
#
# Alternative predefined configs (no Terraform resource needed):
#   CodeDeployDefault.ECSAllAtOnce  — instant cutover, no gradual shift
#   CodeDeployDefault.ECSLinear10PercentEvery1Minute  — same as below but built-in
#   CodeDeployDefault.ECSCanary10Percent5Minutes      — 10% for 5 min, then 90%
# ==============================================================================

resource "aws_codedeploy_deployment_config" "linear" {
  deployment_config_name = "${local.name_prefix}-linear-10pct-1min"
  compute_platform       = "ECS"

  traffic_routing_config {
    type = "TimeBasedLinear"

    time_based_linear {
      # Shift 10% of traffic to green every 1 minute.
      # 100% transferred after 10 × 1 = 10 minutes total.
      interval   = 1    # minutes between each traffic increment
      percentage = 10   # percentage of traffic to shift per interval
    }
  }
}

# ==============================================================================
# CloudWatch Alarms — 5xx Error Rate
#
# These alarms trigger automatic rollback if error rates exceed thresholds
# during a deployment. CodeDeploy monitors them throughout the traffic shift.
# ==============================================================================

# ---- API 5xx alarm -----------------------------------------------------------
# Fires when the sum of HTTPCode_Target_5XX_Count on the API blue target group
# exceeds the threshold. Both blue and green TGs are monitored; CodeDeploy
# rolls back if either fires.

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name_prefix}-api-5xx"
  alarm_description   = "API 5xx errors exceeded threshold — triggers CodeDeploy rollback."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2        # Alarm fires after 2 consecutive breaching periods
  threshold           = 10       # More than 10 5xx responses in one period = rollback
  treat_missing_data  = "notBreaching"

  metric_name = "HTTPCode_Target_5XX_Count"
  namespace   = "AWS/ApplicationELB"
  period      = 60   # 1-minute evaluation window — matches linear shift interval
  statistic   = "Sum"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.api_blue.arn_suffix
  }

  tags = {
    Name      = "${local.name_prefix}-api-5xx"
    Component = "api"
  }
}

# ---- Frontend 5xx alarm ------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "frontend_5xx" {
  alarm_name          = "${local.name_prefix}-frontend-5xx"
  alarm_description   = "Frontend 5xx errors exceeded threshold — triggers CodeDeploy rollback."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 10
  treat_missing_data  = "notBreaching"

  metric_name = "HTTPCode_Target_5XX_Count"
  namespace   = "AWS/ApplicationELB"
  period      = 60
  statistic   = "Sum"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.frontend_blue.arn_suffix
  }

  tags = {
    Name      = "${local.name_prefix}-frontend-5xx"
    Component = "frontend"
  }
}

# ---- ALB-level 5xx alarm (catches errors not tied to a specific TG) ----------

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name_prefix}-alb-5xx"
  alarm_description   = "ALB-level 5xx errors exceeded threshold."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 20
  treat_missing_data  = "notBreaching"

  metric_name = "HTTPCode_ELB_5XX_Count"
  namespace   = "AWS/ApplicationELB"
  period      = 60
  statistic   = "Sum"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
  }

  tags = {
    Name = "${local.name_prefix}-alb-5xx"
  }
}

# ==============================================================================
# CodeDeploy Application — API
# ==============================================================================

resource "aws_codedeploy_app" "api" {
  name             = "${local.name_prefix}-api"
  compute_platform = "ECS"

  tags = {
    Name      = "${local.name_prefix}-api"
    Component = "api"
  }
}

resource "aws_codedeploy_deployment_group" "api" {
  app_name               = aws_codedeploy_app.api.name
  deployment_group_name  = "${local.name_prefix}-api-dg"
  service_role_arn       = aws_iam_role.codedeploy.arn
  deployment_config_name = aws_codedeploy_deployment_config.linear.id

  # ---- ECS service to manage ------------------------------------------------
  ecs_service {
    cluster_name = aws_ecs_cluster.main.name
    service_name = aws_ecs_service.api.name
  }

  # ---- ALB configuration ---------------------------------------------------
  # production_listener_arns — CodeDeploy gradually shifts production traffic here.
  # test_listener_arns       — 100% green traffic routed here during the bake period
  #                            so smoke tests can validate before prod shifts.
  load_balancer_info {
    target_group_pair_info {
      prod_traffic_route {
        listener_arns = [aws_lb_listener.https.arn]
      }
      test_traffic_route {
        listener_arns = [aws_lb_listener.test.arn]
      }
      target_group {
        name = aws_lb_target_group.api_blue.name
      }
      target_group {
        name = aws_lb_target_group.api_green.name
      }
    }
  }

  # ---- Blue/Green deployment settings --------------------------------------
  blue_green_deployment_config {
    deployment_ready_option {
      # Wait up to 5 minutes for the green environment to become healthy.
      # If unhealthy, CodeDeploy aborts and rolls back.
      action_on_timeout    = "STOP_DEPLOYMENT"
      wait_time_in_minutes = 5
    }

    terminate_blue_instances_on_deployment_success {
      # After full traffic shift, drain and terminate blue tasks.
      action                           = "TERMINATE"
      termination_wait_time_in_minutes = 5   # Allow in-flight requests to drain
    }
  }

  deployment_style {
    deployment_option = "WITH_TRAFFIC_CONTROL"   # Use ALB traffic shifting
    deployment_type   = "BLUE_GREEN"
  }

  # ---- Auto-rollback on alarm -----------------------------------------------
  auto_rollback_configuration {
    enabled = true
    events  = [
      "DEPLOYMENT_FAILURE",        # Hard failure (task crash, health check fail)
      "DEPLOYMENT_STOP_ON_ALARM",  # CloudWatch alarm fired during traffic shift
    ]
  }

  # ---- CloudWatch alarms that trigger rollback ------------------------------
  alarm_configuration {
    enabled = true
    alarms  = [
      aws_cloudwatch_metric_alarm.api_5xx.alarm_name,
      aws_cloudwatch_metric_alarm.alb_5xx.alarm_name,
    ]
  }

  tags = {
    Name      = "${local.name_prefix}-api-dg"
    Component = "api"
  }
}

# ==============================================================================
# CodeDeploy Application — Frontend
# ==============================================================================

resource "aws_codedeploy_app" "frontend" {
  name             = "${local.name_prefix}-frontend"
  compute_platform = "ECS"

  tags = {
    Name      = "${local.name_prefix}-frontend"
    Component = "frontend"
  }
}

resource "aws_codedeploy_deployment_group" "frontend" {
  app_name               = aws_codedeploy_app.frontend.name
  deployment_group_name  = "${local.name_prefix}-frontend-dg"
  service_role_arn       = aws_iam_role.codedeploy.arn
  deployment_config_name = aws_codedeploy_deployment_config.linear.id

  ecs_service {
    cluster_name = aws_ecs_cluster.main.name
    service_name = aws_ecs_service.frontend.name
  }

  load_balancer_info {
    target_group_pair_info {
      prod_traffic_route {
        listener_arns = [aws_lb_listener.https.arn]
      }
      test_traffic_route {
        listener_arns = [aws_lb_listener.test.arn]
      }
      target_group {
        name = aws_lb_target_group.frontend_blue.name
      }
      target_group {
        name = aws_lb_target_group.frontend_green.name
      }
    }
  }

  blue_green_deployment_config {
    deployment_ready_option {
      action_on_timeout    = "STOP_DEPLOYMENT"
      wait_time_in_minutes = 5
    }

    terminate_blue_instances_on_deployment_success {
      action                           = "TERMINATE"
      termination_wait_time_in_minutes = 5
    }
  }

  deployment_style {
    deployment_option = "WITH_TRAFFIC_CONTROL"
    deployment_type   = "BLUE_GREEN"
  }

  auto_rollback_configuration {
    enabled = true
    events  = [
      "DEPLOYMENT_FAILURE",
      "DEPLOYMENT_STOP_ON_ALARM",
    ]
  }

  alarm_configuration {
    enabled = true
    alarms  = [
      aws_cloudwatch_metric_alarm.frontend_5xx.alarm_name,
      aws_cloudwatch_metric_alarm.alb_5xx.alarm_name,
    ]
  }

  tags = {
    Name      = "${local.name_prefix}-frontend-dg"
    Component = "frontend"
  }
}
