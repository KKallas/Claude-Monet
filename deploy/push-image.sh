#!/usr/bin/env bash
# From a laptop: build the image for the droplet, send it over SSH, restart.
#   deploy/push-image.sh root@<droplet-ip>
# No registry and no token on the droplet: the image travels through the SSH pipe.
set -euo pipefail
HOST="${1:?usage: push-image.sh user@host}"
cd "$(dirname "$0")/.."
COMMIT="${COMMIT:-$(git rev-parse --short HEAD)}"

docker build --platform linux/amd64 --build-arg COMMIT="$COMMIT" -t monet:"$COMMIT" -t monet:latest .
scp deploy/compose.yml deploy/Caddyfile "$HOST":/opt/monet/
docker save monet:"$COMMIT" monet:latest | gzip | ssh "$HOST" 'gunzip | docker load'
ssh "$HOST" 'cd /opt/monet && docker compose up -d && docker image prune -f >/dev/null && sleep 5 && docker compose ps && docker compose logs --tail 12 app'
