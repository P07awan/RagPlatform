#!/bin/sh
# Make writable directories usable when they are mounted volumes (Docker volumes, Render
# persistent disks), which are often owned by root. Then drop to the unprivileged "app"
# user (uid 10001) before starting the server. If the container is already started as a
# non-root user, the command runs unchanged.
set -e

if [ "$(id -u)" = "0" ]; then
    for dir in "${DATA_DIR:-/app/data}" "${HF_HOME:-/app/.cache/huggingface}"; do
        mkdir -p "$dir"
        chown -R 10001:10001 "$dir"
    done
    exec setpriv --reuid=10001 --regid=10001 --clear-groups "$@"
fi

exec "$@"
