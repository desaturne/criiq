#!/bin/sh
# Two processes in one container: fine for a self-contained demo image, not how
# you'd run this in production (see docker-compose.yml for the proper split).
set -e

cd /app/backend
uvicorn main:app --host 127.0.0.1 --port 8000 &
backend_pid=$!

# If the API dies, take the container down with it rather than serving a UI
# that cannot talk to anything.
trap 'kill $backend_pid 2>/dev/null' TERM INT

exec nginx -g 'daemon off;'
