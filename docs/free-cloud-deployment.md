# 100% Free Cloud Deployment Guide — FAERS Analytics Platform

This guide outlines how to deploy the **FAERS Analytics Platform** to **100% FREE cloud hosting** with **$0.00 monthly cost** and **no credit card required**.

---

## 🏗️ Free Cloud Architecture

```
                    ┌─────────────────────────┐
                    │      Users / Web        │
                    └────────────┬────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │                               │
       ┌─────────▼─────────┐           ┌─────────▼─────────┐
       │   Vercel (UI)     │           │   Render (API)    │
       │   Next.js Host    │           │   FastAPI Web     │
       │  (100% Free Tier) │           │  (100% Free Tier) │
       └───────────────────┘           └─────────┬─────────┘
                                                 │
                                 ┌───────────────┴───────────────┐
                                 │                               │
                       ┌─────────▼─────────┐           ┌─────────▼─────────┐
                       │ Neon / Supabase   │           │   Upstash Redis   │
                       │ PostgreSQL DB     │           │   Cache Engine    │
                       │ (100% Free Tier)  │           │ (100% Free Tier)  │
                       └───────────────────┘           └───────────────────┘
```

| Component | Free Cloud Provider | Free Tier Allowance | Monthly Cost |
| :--- | :--- | :--- | :--- |
| **Frontend UI** | [Vercel](https://vercel.com/) | Unlimited deployments, 100GB bandwidth | **$0.00** |
| **Backend API** | [Render](https://render.com/) | 512 MB RAM Web Service, automatic HTTPS | **$0.00** |
| **PostgreSQL DB** | [Neon](https://neon.tech/) or [Supabase](https://supabase.com/) | 0.5 GiB storage, automated branching | **$0.00** |
| **Redis Cache** | [Upstash](https://upstash.com/) | 10,000 requests/day, serverless Redis | **$0.00** |

---

## 🚀 Step-by-Step Execution Guide

### Step 1: Create a Free Managed PostgreSQL Database (Neon or Supabase)

1. Sign up at [Neon.tech](https://neon.tech/) or [Supabase.com](https://supabase.com/) (1-click GitHub login).
2. Create a new project named `faers-db`.
3. In the SQL Editor / Query Runner, copy and execute the database schema:
   - Paste the contents of [`database/schema.sql`](../database/schema.sql).
   - Paste the contents of [`database/materialized_views.sql`](../database/materialized_views.sql).
4. Copy your database connection string (`DATABASE_URL`). It will look like:
   `postgresql://user:password@ep-xyz.neon.tech/faers?sslmode=require`

---

### Step 2: Create a Free Redis Cache (Upstash)

1. Sign up at [Upstash.com](https://upstash.com/) (1-click GitHub login).
2. Click **Create Database** → Name: `faers-cache`, Type: **Redis**, Region: Primary (e.g. US-East).
3. Copy the **Redis Connection String (`REDIS_URL`)** from the Upstash dashboard:
   `rediss://default:token@xyz.upstash.io:6379`

---

### Step 3: Deploy Backend API to Render

1. Sign up at [Render.com](https://render.com/) using your GitHub account.
2. Click **New +** → **Blueprint** → Select your GitHub repository (`faers`).
3. Render will automatically detect the [`render.yaml`](../render.yaml) file in your root folder.
4. Under **Environment Variables**, enter the following secrets:
   - `DATABASE_URL`: Your connection string from Step 1
   - `REDIS_URL`: Your Redis URL from Step 2
   - `OPENAI_API_KEY`: Your key (or use a free Ollama/Groq endpoint key)
5. Click **Apply**. Render will build the Docker container and deploy the API.
6. Copy your live Render API URL: `https://faers-api.onrender.com`.

---

### Step 4: Deploy Frontend UI to Vercel

1. Sign up at [Vercel.com](https://vercel.com/) with GitHub.
2. Click **Add New...** → **Project** → Select your `faers` repository.
3. Set **Root Directory** to `frontend`.
4. Under **Environment Variables**, add:
   - `NEXT_PUBLIC_API_URL`: `https://faers-api.onrender.com/api/v1`
5. Click **Deploy**. Vercel will build and launch your Next.js frontend in under 60 seconds!

---

## 🔍 Verification & Health Checks

Once deployed, test your live 100% free cloud application:

```bash
# 1. API Liveness Check
curl -i https://faers-api.onrender.com/livez

# 2. API Deep Health Check (DB + Redis probe)
curl -i https://faers-api.onrender.com/health

# 3. Open Frontend UI in Browser
# Visit your Vercel URL (e.g. https://faers-platform.vercel.app)
```
