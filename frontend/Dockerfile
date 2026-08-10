# ── Stage 1: deps ─────────────────────────────────────────────────────────────
# Install only production dependencies. Cached separately from the build stage
# so a source-only change doesn't re-install all packages.
FROM node:20-alpine AS deps

WORKDIR /app

COPY package*.json ./
# --omit=dev keeps devDependencies (TypeScript, ESLint, etc.) out of this layer;
# the builder stage does a full install so it can run `next build`.
RUN npm ci --omit=dev

# ── Stage 2: builder ──────────────────────────────────────────────────────────
# Full install (devDeps needed for tsc, next build) then compile.
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# NEXT_PUBLIC_* vars are baked into the static JS bundle at build time.
# Pass the API URL as a build argument; default is empty so it can also
# be injected by CI (docker build --build-arg NEXT_PUBLIC_API_URL=https://…)
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Disable Next.js telemetry in CI/build environments
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ── Stage 3: runtime ──────────────────────────────────────────────────────────
# Minimal image: only the standalone server bundle — no node_modules, no src.
FROM node:20-alpine AS runner

# Non-root user — never run Node in production as root
RUN addgroup --gid 1001 nodejs \
 && adduser  --uid 1001 --ingroup nodejs --disabled-password --no-create-home nextjs

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
# PORT and HOSTNAME can be overridden at runtime via environment variables;
# no secrets are baked into this image.
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Copy only the self-contained standalone server bundle produced by next build.
# This includes a minimal node_modules tree — no build tools, no src.
COPY --from=builder --chown=nextjs:nodejs /app/public              ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone    ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static        ./.next/static

USER nextjs
EXPOSE 3000

# Next.js standalone exposes /api/health automatically (returns 200 when ready).
# wget is preferred over curl on Alpine because it ships in busybox.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -qO- http://localhost:3000/api/health || exit 1

CMD ["node", "server.js"]
