# ==============================================================================
# ECR — Elastic Container Registry
#
# Two private repositories: faers-api and faers-frontend.
# Images are scanned on every push. A lifecycle policy caps stored images to
# var.ecr_max_image_count to control storage costs.
# ==============================================================================

resource "aws_ecr_repository" "api" {
  name                 = "${local.name_prefix}-api"
  image_tag_mutability = "MUTABLE" # Allow :latest to be overwritten by CI

  image_scanning_configuration {
    scan_on_push = true # Inspector scans every new image for CVEs
  }

  encryption_configuration {
    encryption_type = "AES256" # Default AWS-managed encryption at rest
  }

  tags = {
    Name      = "${local.name_prefix}-api"
    Component = "api"
  }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "${local.name_prefix}-frontend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name      = "${local.name_prefix}-frontend"
    Component = "frontend"
  }
}

# ---- Lifecycle Policies -------------------------------------------------------
# Keep only the N most-recent tagged images; expire untagged layers immediately.
# This prevents unbounded ECR storage growth in active CI pipelines.

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the last ${var.ecr_max_image_count} tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "sha-", "latest"]
          countType     = "imageCountMoreThan"
          countNumber   = var.ecr_max_image_count
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Expire untagged images immediately"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      }
    ]
  })
}

resource "aws_ecr_lifecycle_policy" "frontend" {
  repository = aws_ecr_repository.frontend.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the last ${var.ecr_max_image_count} tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "sha-", "latest"]
          countType     = "imageCountMoreThan"
          countNumber   = var.ecr_max_image_count
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Expire untagged images immediately"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      }
    ]
  })
}
