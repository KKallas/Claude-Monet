#!/usr/bin/env bash
# Put an older image back:   deploy/rollback.sh root@<droplet-ip> <commit>
# (the droplet keeps the images it was sent until they are pruned: `docker images monet`)
set -euo pipefail
HOST="${1:?usage: rollback.sh user@host <commit>}"; COMMIT="${2:?which commit?}"
ssh "$HOST" "docker tag monet:$COMMIT monet:latest && cd /opt/monet && docker compose up -d && docker compose ps"
