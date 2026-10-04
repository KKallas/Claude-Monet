"""monet: run the server.

    monet                      on http://localhost:8000, working files in ./storage
    monet --port 8080 --storage /storage --max-users 30

The same settings from the environment: PORT, MONET_HOST, MONET_STORAGE, MONET_MAX_USERS,
MONET_BASE_URL (the public address, behind a proxy), MONET_NOTE (a line shown on the
start page).
"""
import argparse
import os

import uvicorn

from .app import create_app


def main():
    ap = argparse.ArgumentParser(prog="monet", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("MONET_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    ap.add_argument("--storage", default=os.environ.get("MONET_STORAGE", "storage"))
    ap.add_argument("--max-users", type=int, default=int(os.environ.get("MONET_MAX_USERS", "20")))
    args = ap.parse_args()
    app = create_app(args.storage, args.max_users)
    print(f"Monet on http://{args.host}:{args.port} · working files in {os.path.abspath(args.storage)} · "
          f"{app.state.workspaces.count()} of {args.max_users} workspaces in use")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", proxy_headers=True,
                forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"))


if __name__ == "__main__":
    main()
