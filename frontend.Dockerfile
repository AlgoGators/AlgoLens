# ---------- Build stage ----------
FROM node:20-alpine AS build
WORKDIR /app

# Some Next.js deps need this on Alpine
RUN apk add --no-cache libc6-compat

# Install deps (clean, reproducible)
COPY frontend/package*.json ./
RUN npm ci

# Copy source and build
COPY frontend/ ./
# If you need build-time envs, add:
# ARG NEXT_PUBLIC_API_URL
# ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

# ---------- Runtime stage ----------
FROM node:20-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000 \
    NEXT_TELEMETRY_DISABLED=1

# Copy only what’s needed to run
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/package*.json ./

# Install only production deps
RUN npm ci --omit=dev

EXPOSE 3000
CMD ["npm", "run", "start"]
