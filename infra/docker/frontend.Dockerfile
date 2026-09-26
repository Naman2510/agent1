# syntax=docker/dockerfile:1
# Next.js standalone output: the runtime image carries the server and only the modules it traces.

FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
# Where the *browser* reaches the backend. NEXT_PUBLIC_ values are inlined into the bundle at build
# time, so this is a build argument, not a runtime setting.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-bookworm-slim AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app

# Non-root, matching the backend image.
RUN groupadd --gid 10001 vaanios \
    && useradd --uid 10001 --gid vaanios --create-home --shell /usr/sbin/nologin vaanios

COPY --from=build --chown=vaanios:vaanios /app/.next/standalone ./
COPY --from=build --chown=vaanios:vaanios /app/.next/static ./.next/static
COPY --from=build --chown=vaanios:vaanios /app/public ./public

USER vaanios
EXPOSE 3000
CMD ["node", "server.js"]
