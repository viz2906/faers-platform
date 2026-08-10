terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Uncomment and configure to store state remotely (recommended for teams):
  # backend "s3" {
  #   bucket         = "faers-terraform-state"
  #   key            = "network/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "faers-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "faers-platform"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}

provider "aws" {
  alias  = "dr"
  region = var.dr_aws_region

  default_tags {
    tags = {
      Project     = "faers-platform"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}

