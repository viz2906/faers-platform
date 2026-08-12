# ==============================================================================
# ECS Service Auto Scaling (Fargate)
#
# ------------------------------------------------------------------------------
# Architectural Note: ECS Service Auto Scaling vs. EC2 Auto Scaling Groups
# ------------------------------------------------------------------------------
# In traditional EC2-based ECS clusters, autoscaling operates at two distinct layers:
#   1. Instance-Level Scaling (EC2 Auto Scaling Groups / ASGs):
#      Provisions or terminates underlying EC2 virtual machine instances when cluster
#      CPU/memory capacity is exhausted.
#   2. Task-Level Scaling (ECS Service Auto Scaling):
#      Adds or removes container tasks (pods/instances of your app) on top of the
#      available EC2 instances.
#
# Because this architecture uses AWS Fargate (Serverless Compute for Containers):
#   - EC2 Auto Scaling Groups are COMPLETELY UNNECESSARY.
#   - AWS manages, provisions, and scales all underlying host infrastructure serverlessly.
#   - You only define Application Auto Scaling targets and policies at the ECS task level.
#   - Fargate seamlessly allocates host capacity for each new container task on demand.
# ==============================================================================

# ==============================================================================
# Auto Scaling Target — API Service (Min: 2, Max: 6)
# ==============================================================================

resource "aws_appautoscaling_target" "api" {
  max_capacity       = var.ecs_max_capacity
  min_capacity       = var.ecs_min_capacity
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# ==============================================================================
# Auto Scaling Target — Frontend Service (Min: 2, Max: 6)
# ==============================================================================

resource "aws_appautoscaling_target" "frontend" {
  max_capacity       = var.ecs_max_capacity
  min_capacity       = var.ecs_min_capacity
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.frontend.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# ==============================================================================
# Policy 1: Target Tracking — CPU Utilization at 60% (API)
# ==============================================================================

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${local.name_prefix}-api-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }

    target_value       = var.autoscaling_cpu_target
    scale_in_cooldown  = 300 # Wait 5 minutes before scaling down to prevent flapping
    scale_out_cooldown = 60  # Scale out rapidly (1 minute) during traffic spikes
  }
}

# ==============================================================================
# Policy 2: Target Tracking — CPU Utilization at 60% (Frontend)
# ==============================================================================

resource "aws_appautoscaling_policy" "frontend_cpu" {
  name               = "${local.name_prefix}-frontend-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.frontend.resource_id
  scalable_dimension = aws_appautoscaling_target.frontend.scalable_dimension
  service_namespace  = aws_appautoscaling_target.frontend.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }

    target_value       = var.autoscaling_cpu_target
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# ==============================================================================
# Policy 3: Target Tracking — ALB Request Count per Target (API Service)
# ==============================================================================
# Scales the API service based on incoming HTTP request volume per task target.
# Tracks requests hitting the primary active target group via ALB.

resource "aws_appautoscaling_policy" "api_alb_requests" {
  name               = "${local.name_prefix}-api-alb-request-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      # Formatted as app/<alb-name>/<alb-id>/targetgroup/<tg-name>/<tg-id>
      resource_label = "${aws_lb.main.arn_suffix}/${aws_lb_target_group.api_blue.arn_suffix}"
    }

    target_value       = var.autoscaling_alb_target_requests
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
