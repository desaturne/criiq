# --- Stage 1: build the static bundle ---------------------------------------
FROM node:24-slim AS builder

WORKDIR /app

# Lockfile first, so dependency installs stay cached across code edits
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite inlines this at BUILD time — it cannot be changed at runtime
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# --- Stage 2: serve it -------------------------------------------------------
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
