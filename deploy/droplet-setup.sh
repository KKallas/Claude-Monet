#!/usr/bin/env bash
# Run ONCE on a fresh Ubuntu droplet, as root:   bash droplet-setup.sh monet.example.org
# Installs Docker, a firewall, swap, and lays out /opt/monet. The image itself arrives from
# `deploy/push-image.sh` on a laptop.
set -euo pipefail
DOMAIN="${1:?usage: droplet-setup.sh <domain>}"

apt-get update -y
apt-get install -y ca-certificates curl ufw unattended-upgrades
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sh; fi

# 2 GB of swap: a safety net on a small droplet (the CAD kernel is hungry), not something to live on
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

mkdir -p /opt/monet/storage
# the container runs as uid 1000 (monet)
chown 1000:1000 /opt/monet/storage && chmod 700 /opt/monet/storage
[ -f /opt/monet/.env ] || echo "DOMAIN=${DOMAIN}" > /opt/monet/.env
echo "Ready. Now, from the laptop: deploy/push-image.sh root@<this droplet>   (see docs/SETUP-ONLINE.md)"
