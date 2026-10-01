#!/bin/sh
set -e

# exec so python becomes PID 1 and receives SIGTERM from `docker stop`
exec python /app/app.py "$@"
