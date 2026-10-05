#!/usr/bin/env bash
# From a laptop or from CI: build the image for the droplet, send it over SSH, restart.
#   deploy/push-image.sh root@<droplet-ip>
# No registry and no token on the droplet: the image travels through the SSH pipe.
set -euo pipefail
HOST="${1:?usage: push-image.sh user@host}"
cd "$(dirname "$0")/.."
COMMIT="${COMMIT:-$(git rev-parse --short HEAD)}"

docker build --platform linux/amd64 --build-arg COMMIT="$COMMIT" -t monet:"$COMMIT" -t monet:latest .

# One connection for everything, opened patiently: a public droplet's SSH port is knocked on all day, and sshd
# drops newcomers when too many are waiting. Once it is open, the rest rides on it.
CM="$(mktemp -d)/cm"
SSH=(-o ControlMaster=auto -o "ControlPath=$CM" -o ControlPersist=180 -o ConnectTimeout=20)
trap 'ssh "${SSH[@]}" -O exit "$HOST" 2>/dev/null || true' EXIT
for try in $(seq 1 15); do ssh "${SSH[@]}" "$HOST" true 2>/dev/null && break; [ "$try" = 15 ] && { echo "could not reach $HOST"; exit 1; }; sleep 4; done

# The proxy's file is tried before it is put in place (a bad one would take the site down), and written into the
# file that is there, since the proxy has that very file mounted.
scp "${SSH[@]}" deploy/compose.yml "$HOST":/opt/monet/
scp "${SSH[@]}" deploy/Caddyfile "$HOST":/opt/monet/Caddyfile.new
ssh "${SSH[@]}" "$HOST" 'cd /opt/monet && docker run --rm -e DOMAIN=check.invalid -v /opt/monet/Caddyfile.new:/etc/caddy/Caddyfile:ro caddy:2 caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 && cat Caddyfile.new > Caddyfile && rm Caddyfile.new'
docker save monet:"$COMMIT" monet:latest | gzip | ssh "${SSH[@]}" "$HOST" 'gunzip | docker load'
ssh "${SSH[@]}" "$HOST" 'cd /opt/monet && docker compose up -d --remove-orphans && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 && docker image prune -f >/dev/null && sleep 6 && docker compose ps && docker compose logs --tail 12 app'
