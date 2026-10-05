# Putting an instance online

One droplet, Docker, Caddy for HTTPS. About 20 minutes the first time. Read "Running it for
other people" in the README first: an instance runs the code people send it.

## 1. The droplet

DigitalOcean → Create → Droplet: Ubuntu 24.04, **2 GB / 1 vCPU** or larger (the CAD kernel wants
memory; 1 GB is too little), SSH key, hostname `monet`. Use a droplet that holds nothing else.
Assign a Reserved IP so the address survives rebuilding the droplet.

## 2. The name

An A record for the name you want (say `monet.example.org`) pointing at the reserved IP, in the
DNS zone where the domain already lives. It must resolve before step 4: Caddy asks Let's Encrypt
for the certificate on first start.

```bash
dig +short monet.example.org
```

## 3. Prepare the droplet (once)

```bash
IP=<the droplet's address>
scp deploy/droplet-setup.sh root@$IP:
ssh root@$IP bash droplet-setup.sh monet.example.org
```

Installs Docker, unattended security updates, a firewall (22, 80, 443 only), 2 GB of swap, and
makes `/opt/monet` with `storage/` and `.env`. Settings go in `/opt/monet/.env`
(`deploy/env.example`): `MONET_MAX_USERS` is how many workspaces there may be, `MONET_NOTE` a line
shown on the start page.

## 4. Send the image

From the laptop, with Docker running:

```bash
deploy/push-image.sh root@$IP
```

Builds the image for linux/amd64 (slow on an Apple Silicon laptop: it is emulated), sends it
through the SSH pipe, copies `compose.yml` and `Caddyfile`, starts everything. The same command
deploys every later version. `deploy/rollback.sh root@$IP <commit>` puts an older one back.

## 5. The admin, and letting people in

The first time the app starts it has one account, the built-in admin, without a password. Its log
says where to choose one:

```bash
ssh root@$IP 'cd /opt/monet && docker compose logs app | grep -A1 "no password yet"'
```

Open that link once. Then `https://<domain>/users`: add a user, send them their card link (or let
them scan the QR), and they choose their own password on the first visit. Everything about accounts
is in `/opt/monet/data` (`users.json`, the audit log `log.jsonl`, the session secret); the container
that builds Notes does not have that folder.

## Check

- `https://monet.example.org` shows the login page.
- Log in, open `starter/rod_foot`: the part appears (built by the `runner` container).
- `https://monet.example.org/api` is the page to point an LLM at.
- Claude Desktop → Settings → Connectors → Add custom connector → the address from
  "Connect your agent" in the canvas.

## Looking after it

- **Full?** `MONET_MAX_USERS` in `.env` is how many users there may be; delete one on `/users` and
  the place is free. Their files stay in `/opt/monet/storage/<user id>` until removed by hand.
- **Backups**: what people made is in `/opt/monet/storage`, who they are in `/opt/monet/data`.
  Nothing else on the droplet matters; it can be rebuilt from this repository.
- **Logs**: `cd /opt/monet && docker compose logs --tail 100 app`.
- The app container has no route to the internet by design (`internal: true` in
  `compose.yml`). The canvas loads three.js from a CDN in the visitor's browser, not through
  the server.
