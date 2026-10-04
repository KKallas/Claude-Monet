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

## 5. Check

- `https://monet.example.org` shows the start page and "0 of 20 workspaces in use".
- Press Start, open `starter/rod_foot`: the part appears.
- `https://monet.example.org/api` is the page to point an LLM at.
- Claude Desktop → Settings → Connectors → Add custom connector → the address from
  "Connect your agent" in the canvas.

## Looking after it

- **Full?** Workspaces are folders: `ls -lt /opt/monet/storage` shows them, oldest last. Delete
  the folder of one nobody uses and its slot is free. Nothing is removed automatically.
- **Backups**: everything people made is in `/opt/monet/storage`. Nothing else on the droplet
  matters; it can be rebuilt from this repository.
- **Logs**: `cd /opt/monet && docker compose logs --tail 100 app`.
- The app container has no route to the internet by design (`internal: true` in
  `compose.yml`). The canvas loads three.js from a CDN in the visitor's browser, not through
  the server.
