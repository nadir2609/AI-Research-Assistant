
#!/bin/sh
set -e

if [ -n "${DATABASE_URL:-}" ]; then
  python /app/docker/wait_for_db.py
  python /app/docker/verify_stack.py
fi

exec "$@"
