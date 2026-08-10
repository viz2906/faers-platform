# FAERS Analytics Platform — Architecture & Dataflow Diagrams

This document provides visual architecture and dataflow diagrams for team reviews, client meetings, and system documentation. The Mermaid code blocks below can be pasted directly into [Draw.io](https://app.diagrams.net/) (via `Insert → Advanced → Mermaid`) or viewed on GitHub.

---

## 1. System Deployment Architecture (AWS ECS Fargate & Network Security)

```mermaid
flowchart TD
    subgraph Internet ["🌐 Internet / Clients"]
        Users["Users & Browsers"]
        GitHub["GitHub Actions CI/CD"]
    end

    subgraph AWS ["☁️ AWS Cloud Region (us-east-1)"]
        subgraph PublicSubnets ["Public Subnets (2 AZs - 10.0.0.0/24, 10.0.1.0/24)"]
            DNS["Route 53 DNS + ACM TLS Cert"]
            ALB["Application Load Balancer (alb_sg)"]
            NAT["Single NAT Gateway"]
        end

        subgraph ECSSubnets ["Private ECS Subnets (2 AZs - 10.0.10.0/24, 10.0.11.0/24)"]
            subgraph FargateCluster ["ECS Fargate Cluster (ecs_sg)"]
                subgraph APIService ["FastAPI Backend Service"]
                    APITasks["API Tasks (Min: 2, Max: 6)\nPort 8000"]
                end
                subgraph FEService ["Next.js Frontend Service"]
                    FETasks["Frontend Tasks (Min: 2, Max: 6)\nPort 3000"]
                end
            end
        end

        subgraph DBSubnets ["Private DB Subnets (2 AZs - 10.0.20.0/24, 10.0.21.0/24)"]
            RDS[("PostgreSQL 16 RDS\n(db_sg - Port 5432)")]
            Redis[("ElastiCache Redis 7.2\n(db_sg - Port 6379)")]
        end

        subgraph Management ["Management & Observability"]
            Secrets["AWS Secrets Manager\n(Encrypted DB/Redis Credentials)"]
            ECR["Amazon ECR\n(faers-api & faers-frontend Repos)"]
            CodeDeploy["AWS CodeDeploy\n(Blue/Green 10%/min Linear Shift)"]
            Backup["AWS Backup\n(Weekly Copy to us-west-2)"]
            Logs["CloudWatch Logs & 5xx Alarms"]
        end
    end

    Users -->|HTTPS :443| DNS
    DNS --> ALB
    ALB -->|/api/*| APITasks
    ALB -->|/*| FETasks

    APITasks -->|SQL Queries| RDS
    APITasks -->|Cache Get/Set| Redis
    APITasks -->|Outbound LLM Calls| NAT
    NAT -->|Internet Egress| Internet

    APITasks -.->|Fetch Credentials| Secrets
    FETasks -.->|Fetch Credentials| Secrets

    GitHub -->|OIDC Auth / Push Images| ECR
    GitHub -->|Trigger Blue/Green| CodeDeploy
    CodeDeploy -->|Swap Target Groups| ALB
    Logs -.->|Auto-Rollback Trigger| CodeDeploy
```

---

## 2. Natural Language Query Dataflow Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Browser
    participant ALB as ALB / Caddy Reverse Proxy
    participant API as FastAPI Backend (/api/v1/nlp/query)
    participant Cache as Redis Cache (Port 6379)
    participant Router as Query Classifier / Router
    participant LLM as LLM Engine (OpenAI / Ollama)
    participant DB as TimescaleDB / PostgreSQL (Port 5432)

    User->>ALB: POST /api/v1/nlp/query {"question": "top adverse reactions for warfarin"}
    ALB->>API: Proxy request to FastAPI backend container
    API->>Cache: Check Redis for cached response (SHA256 question hash)

    alt Cache Hit
        Cache-->>API: Return cached JSON payload
        API-->>User: Return 200 OK (from_cache: true, response_time < 20ms)
    else Cache Miss
        Cache-->>API: Key not found
        API->>Router: Classify question pattern
        alt Hardcoded / Materialized View Pattern Match
            Router-->>API: Match: mv_drug_reaction_pairs
            API->>DB: Execute pre-compiled SQL query against Materialized View
            DB-->>API: Return result dataset
        else Complex / Raw Table Pattern
            Router-->>API: Dynamic SQL required
            API->>LLM: Generate SQL from schema context (Prompt + Schema)
            LLM-->>API: Return generated SELECT query
            API->>API: Validate SQL against AST security rules
            API->>DB: Execute validated SQL query (with 5s statement timeout)
            DB-->>API: Return result dataset
        end
        API->>Cache: Store result JSON in Redis (TTL: 3600s)
        API-->>User: Return 200 OK (data, SQL, row_count, response_time_ms)
    end
```

---

## 3. Disaster Recovery (DR) & RTO / RPO Flow

```mermaid
flowchart LR
    subgraph Incident ["💥 Outage / Crash Detected"]
        Crash["Primary DB Failure / Data Corruption"]
    end

    subgraph RestoreProcess ["⏱️ Recovery Process (RTO Target: < 1 Hour)"]
        Step1["1. Identify Failure & Latest Snapshot / Point-In-Time (RPO <= 15 min WAL)"]
        Step2["2. Restore RDS Database (PITR or Snapshot)"]
        Step3["3. Re-point Secrets Manager Host Payload"]
        Step4["4. Force ECS New Service Deployment"]
        Step5["5. Health Check Verification (/livez & /health)"]
    end

    Incident --> Step1
    Step1 --> Step2
    Step2 --> Step3
    Step3 --> Step4
    Step4 --> Step5
```

---

## Summary Checklist of Required Features

| Requirement | Implementation Status | Location in Codebase |
| :--- | :--- | :--- |
| **SSL Certificate** | ✅ Fulfilled | [Caddyfile](../Caddyfile) (Auto Let's Encrypt) & [acm.tf](../terraform/acm.tf) |
| **HTTPS** | ✅ Fulfilled | `Caddyfile` (HTTP 80 → 443) & [alb.tf](../terraform/alb.tf) (301 Redirect) |
| **GitHub Actions** | ✅ Fulfilled | [.github/workflows/ci.yml](../.github/workflows/ci.yml) & [deploy.yml](../.github/workflows/deploy.yml) |
| **Terraform** | ✅ Fulfilled | Entire [terraform/](../terraform/) directory (14 `.tf` configuration files) |
| **ECS / EKS** | ✅ Fulfilled | [ecs.tf](../terraform/ecs.tf) (Fargate Cluster, Task Definitions, Services) |
| **Subnets** | ✅ Fulfilled | [network.tf](../terraform/network.tf) (6 subnets across 2 Availability Zones) |
| **VPC & Security** | ✅ Fulfilled | `network.tf` (VPC, IGW, NAT, 3-tier Security Groups `alb_sg`, `ecs_sg`, `db_sg`) |
| **Blue/Green Deployment** | ✅ Fulfilled | [codedeploy.tf](../terraform/codedeploy.tf) & `deploy.yml` (CodeDeploy 10%/min linear shift) |
| **Disaster Recovery** | ✅ Fulfilled | [docs/disaster-recovery.md](disaster-recovery.md) & [scripts/dr-drill.sh](../scripts/dr-drill.sh) |
| **RTO & RPO** | ✅ Fulfilled | Documented: **RTO = 1 Hour**, **RPO = 15 Minutes** (continuous WAL logs) |
| **Crash RTO/RPO Speed** | ✅ Fulfilled | Automated PITR restore (< 15 min data loss, < 1 hr full service recovery) |
| **Auto Scaling Groups** | ✅ Fulfilled | [autoscaling.tf](../terraform/autoscaling.tf) (ECS Target Tracking 60% CPU & ALB requests) |
| **Dataflow / Architecture Diagrams** | ✅ Fulfilled | Documented in this file (`docs/architecture-diagrams.md`) |
| **ECR & ECS Deployment** | ✅ Fulfilled | [ecr.tf](../terraform/ecr.tf), `ecs.tf`, and `.github/workflows/deploy.yml` |
