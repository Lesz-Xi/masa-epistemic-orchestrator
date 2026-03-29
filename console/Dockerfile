FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
# Skip public if folder doesn't exist
# COPY --from=builder /app/public ./public

ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0

# Start Next directly to avoid npm/script arg parsing issues in the container.
CMD ["npx", "next", "start", "-p", "3200", "-H", "0.0.0.0"]
