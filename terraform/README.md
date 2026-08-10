# terraform/ — FAERS Platform AWS Network

Terraform configuration for the **FAERS Analytics Platform** AWS network layer.
Provisions a production-grade VPC with public, private ECS, and private DB subnet tiers across two availability zones.

---

## Architecture Overview

```
                        Internet
                           │
                    ┌──────┴──────┐
                    │     ALB     │  (public subnets — 10.0.0.x / 10.0.1.x)
                    │   alb_sg    │  ← port 443/80 from 0.0.0.0/0
                    └──────┬──────┘
                           │
              ┌────────────┴────────────┐
              │                         │
       ┌──────┴──────┐           ┌──────┴──────┐
       │  ECS Tasks  │           │  ECS Tasks  │  (private ECS subnets — 10.0.10.x / 10.0.11.x)
       │   ecs_sg    │           │   ecs_sg    │  ← traffic only from alb_sg
       └──────┬──────┘           └──────┬──────┘
              │ NAT egress               │
              └────────────┬────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
       ┌──────┴──────┐           ┌──────┴──────┐
       │  RDS / Redis│           │  RDS / Redis│  (private DB subnets — 10.0.20.x / 10.0.21.x)
       │    db_sg    │           │    db_sg    │  ← ports 5432/6379 only from ecs_sg
       └─────────────┘           └─────────────┘
```

### Cost-Control Decision: Single NAT Gateway

One NAT gateway is used (in AZ-a) rather than one per AZ. This saves ~$32/month per AZ in NAT costs. The trade-off is that if AZ-a is unavailable, ECS tasks in AZ-b lose internet egress (image pulls, LLM API calls). For production HA, add a second NAT by duplicating the EIP + NAT gateway resources and pointing `ecs_rt` for AZ-b at the second NAT.

---

## Prerequisites

| Tool | Minimum version |
|------|----------------|
| [Terraform](https://developer.hashicorp.com/terraform/downloads) | 1.6.0 |
| [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) | 2.x |

AWS credentials must be available in the environment. The simplest approach:

```bash
# Option A — environment variables
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1

# Option B — AWS CLI profile
aws configure --profile faers
export AWS_PROFILE=faers
```

---

## Quick Start

```bash
# 1. Enter the terraform directory
cd terraform/

# 2. Copy and edit the variables file
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set aws_region, environment, CIDRs as needed

# 3. Initialise Terraform (downloads the AWS provider)
terraform init

# 4. Preview changes — read this carefully before applying
terraform plan -out=tfplan

# 5. Apply (creates ~20 AWS resources; takes ~2–3 minutes)
terraform apply tfplan
```

After a successful apply, Terraform prints the output values (VPC ID, subnet IDs, security group IDs) needed by downstream modules (ECS, RDS, ElastiCache, ALB).

```bash
# View outputs at any time
terraform output
```

---

## Variable Reference

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `aws_region` | string | `us-east-1` | AWS region for all resources |
| `environment` | string | `prod` | Label applied to every resource tag (`dev` / `staging` / `prod`) |
| `project` | string | `faers` | Short name prefix in resource names |
| `vpc_cidr` | string | `10.0.0.0/16` | CIDR block for the VPC |
| `availability_zones` | list(string) | `["a","b"]` | 2 AZ suffixes combined with `aws_region` |
| `public_subnet_cidrs` | list(string) | `["10.0.0.0/24","10.0.1.0/24"]` | CIDRs for ALB / NAT public subnets |
| `ecs_subnet_cidrs` | list(string) | `["10.0.10.0/24","10.0.11.0/24"]` | CIDRs for ECS task private subnets |
| `db_subnet_cidrs` | list(string) | `["10.0.20.0/24","10.0.21.0/24"]` | CIDRs for RDS / ElastiCache private subnets |

---

## Remote State (Recommended for Teams)

Using local state (`terraform.tfstate`) is fine for exploration but risks state loss and concurrent-edit conflicts in teams. Uncomment the `backend "s3"` block in [versions.tf](versions.tf) and create the bucket + DynamoDB table first:

```bash
# Create the state bucket (one-time setup — do NOT use Terraform for this)
aws s3api create-bucket --bucket faers-terraform-state --region us-east-1
aws s3api put-bucket-versioning \
    --bucket faers-terraform-state \
    --versioning-configuration Status=Enabled
aws dynamodb create-table \
    --table-name faers-terraform-locks \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region us-east-1
```

Then re-run `terraform init` to migrate local state to S3.

---

## Tearing Down (Test / Dev Environments)

> [!WARNING]
> `terraform destroy` is irreversible. Ensure you have no production data in any dependent resources (RDS snapshots, ECS services) before running this.

```bash
# Preview what will be deleted
terraform plan -destroy -out=destroy-plan

# Destroy all resources in this module
terraform apply destroy-plan
```

If dependent resources (e.g. ECS services, RDS instances) were created in other modules, destroy those **first** before destroying the network layer, otherwise you will see dependency errors.

---

## Files in This Directory

| File | Purpose |
|------|---------|
| [versions.tf](versions.tf) | Terraform and AWS provider version pins |
| [variables.tf](variables.tf) | All input variable definitions |
| [network.tf](network.tf) | VPC, subnets, IGW, NAT, route tables, security groups |
| [outputs.tf](outputs.tf) | Exported IDs for downstream modules |
| [terraform.tfvars.example](terraform.tfvars.example) | Example variable values — copy to `terraform.tfvars` |
