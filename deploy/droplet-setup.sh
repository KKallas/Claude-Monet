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

# a public droplet is knocked on all day: keys only, and room for our own connections among the knocking
cat > /etc/ssh/sshd_config.d/10-monet.conf <<'EOT'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
MaxStartups 100:30:300
LoginGraceTime 20
MaxAuthTries 3
EOT
sshd -t && systemctl reload ssh

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

mkdir -p /opt/monet/storage /opt/monet/data
# the containers run as uid 1000 (monet): storage is the working files, data the accounts
chown 1000:1000 /opt/monet/storage /opt/monet/data && chmod 700 /opt/monet/storage /opt/monet/data
[ -f /opt/monet/.env ] || echo "DOMAIN=${DOMAIN}" > /opt/monet/.env
echo "Ready. Now, from the laptop: deploy/push-image.sh root@<this droplet>   (see docs/SETUP-ONLINE.md)"
