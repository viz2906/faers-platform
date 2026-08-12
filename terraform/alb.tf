# ==============================================================================
# ALB — Application Load Balancer  (Blue/Green Edition)
#
# Blue/Green deployments via CodeDeploy require:
#   1. TWO target groups per service (blue = live, green = new version).
#      CodeDeploy shifts traffic between them; Terraform must not manage which
#      one is "active" — that state lives in CodeDeploy.
#   2. A PRODUCTION listener (443) — CodeDeploy swaps its forwarding rule.
#   3. A TEST listener (8080) — CodeDeploy routes 100% to green here first so
#      integration/smoke tests can run before any prod traffic shifts.
#
# Naming convention:
#   aws_lb_target_group.<service>_blue  — starts as the live target group
#   aws_lb_target_group.<service>_green — starts as the standby target group
#
# ⚠️  After the first CodeDeploy deployment, Terraform will no longer control
#     which TG is active on the HTTPS listener default action / listener rule.
#     Add lifecycle { ignore_changes = [default_action] } to the listener
#     resources below — CodeDeploy owns that state.
# ==============================================================================

resource "aws_lb" "main" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  # access_logs {
  #   bucket  = "faers-alb-access-logs"
  #   prefix  = local.name_prefix
  #   enabled = true
  # }

  enable_deletion_protection = true
  idle_timeout               = 60
  enable_http2               = true
  drop_invalid_header_fields = true

  tags = {
    Name = "${local.name_prefix}-alb"
  }
}

# ==============================================================================
# Security Group — allow test listener port 8080 from internet
# ==============================================================================
# The test listener must be reachable so CodeDeploy (and optionally CI smoke
# tests) can validate the green environment before traffic shifts.

resource "aws_security_group_rule" "alb_test_listener" {
  type              = "ingress"
  from_port         = 8080
  to_port           = 8080
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.alb.id
  description       = "CodeDeploy test listener - green environment validation"
}

# ==============================================================================
# Target Groups — API (Blue & Green)
# ==============================================================================

resource "aws_lb_target_group" "api_blue" {
  name        = "${local.name_prefix}-api-blue"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    enabled             = true
    path                = "/livez"
    protocol            = "HTTP"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30

  tags = {
    Name      = "${local.name_prefix}-api-blue"
    Component = "api"
    Slot      = "blue"
  }
}

resource "aws_lb_target_group" "api_green" {
  name        = "${local.name_prefix}-api-green"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    enabled             = true
    path                = "/livez"
    protocol            = "HTTP"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30

  tags = {
    Name      = "${local.name_prefix}-api-green"
    Component = "api"
    Slot      = "green"
  }
}

# ==============================================================================
# Target Groups — Frontend (Blue & Green)
# ==============================================================================

resource "aws_lb_target_group" "frontend_blue" {
  name        = "${local.name_prefix}-fe-blue"
  port        = 3000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    enabled             = true
    path                = "/"
    protocol            = "HTTP"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30

  tags = {
    Name      = "${local.name_prefix}-fe-blue"
    Component = "frontend"
    Slot      = "blue"
  }
}

resource "aws_lb_target_group" "frontend_green" {
  name        = "${local.name_prefix}-fe-green"
  port        = 3000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    enabled             = true
    path                = "/"
    protocol            = "HTTP"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30

  tags = {
    Name      = "${local.name_prefix}-fe-green"
    Component = "frontend"
    Slot      = "green"
  }
}

# ==============================================================================
# Listeners
# ==============================================================================

# ---- HTTP (80) — production / HTTP listener ----------------------------------
# When enable_https = true:  301-redirects all traffic to port 443 (HTTPS).
# When enable_https = false: forwards directly to the frontend blue target group.

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = var.enable_https ? "redirect" : "forward"
    target_group_arn = var.enable_https ? null : aws_lb_target_group.frontend_blue.arn

    dynamic "redirect" {
      for_each = var.enable_https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }

  tags = {
    Name = "${local.name_prefix}-http-listener"
  }

  lifecycle {
    ignore_changes = [default_action]
  }
}

# ---- HTTPS (443) — PRODUCTION listener (gated on enable_https = true) --------
# Only provisioned when var.enable_https = true.
# After the first CodeDeploy deployment, CodeDeploy manages the active TG.

resource "aws_lb_listener" "https" {
  count = var.enable_https ? 1 : 0

  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.main[0].certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend_blue.arn
  }

  tags = {
    Name = "${local.name_prefix}-https-listener"
  }

  lifecycle {
    # CodeDeploy swaps the forwarding target; Terraform must not fight it.
    ignore_changes = [default_action]
  }
}

# ---- Listener Rule — API paths → API blue TG (priority 10) ------------------
# Attached to HTTPS listener when enable_https = true, or HTTP listener when false.

resource "aws_lb_listener_rule" "api" {
  listener_arn = var.enable_https ? aws_lb_listener.https[0].arn : aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api_blue.arn
  }

  condition {
    path_pattern {
      values = [
        "/api/*",
        "/docs*",
        "/redoc*",
        "/openapi.json",
        "/livez",
      ]
    }
  }

  tags = {
    Name = "${local.name_prefix}-api-listener-rule"
  }

  lifecycle {
    ignore_changes = [action]
  }
}

# ---- TEST listener (8080) — GREEN environment validation --------------------
# CodeDeploy routes 100% of test traffic here before touching the prod listener.
# The CI/CD smoke-test step (or CodeDeploy hooks) can call port 8080 to
# validate the new version before committing the traffic shift.
#
# Initial default → frontend green.  After first deployment, CodeDeploy owns it.

resource "aws_lb_listener" "test" {
  load_balancer_arn = aws_lb.main.arn
  port              = 8080
  protocol          = "HTTP" # No TLS — test listener is internal validation only

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend_green.arn
  }

  tags = {
    Name = "${local.name_prefix}-test-listener"
  }

  lifecycle {
    ignore_changes = [default_action]
  }
}

# ---- TEST Listener Rule — API green TG (priority 10) -------------------------

resource "aws_lb_listener_rule" "api_test" {
  listener_arn = aws_lb_listener.test.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api_green.arn
  }

  condition {
    path_pattern {
      values = [
        "/api/*",
        "/docs*",
        "/redoc*",
        "/openapi.json",
        "/livez",
      ]
    }
  }

  tags = {
    Name = "${local.name_prefix}-api-test-listener-rule"
  }

  lifecycle {
    ignore_changes = [action]
  }
}
