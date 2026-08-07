# CanI web app (Next.js standalone). Built from the repo root context (see
# .github/workflows/app-cd-dev.yml), like the service Dockerfiles.

# --- build ---------------------------------------------------------------------
FROM node:20-alpine AS builder
WORKDIR /app
# Copy all source first
COPY apps/web/ ./
# Install deps and build (this ensures node_modules has correct permissions)
RUN npm ci && npm run build

# --- runtime -------------------------------------------------------------------
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1
# Non-root, matching the uid the pod securityContext expects.
RUN addgroup -g 10001 app && adduser -u 10001 -G app -S -H app
# The standalone server + its static assets (Next does not fold static into standalone).
COPY --from=builder --chown=10001:10001 /app/.next/standalone ./
COPY --from=builder --chown=10001:10001 /app/.next/static ./.next/static
USER 10001
EXPOSE 3000
CMD ["node", "server.js"]
