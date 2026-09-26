# Deploying the KAVACH platform on an Ubuntu server (Docker Compose)

Result: users open `http://<server-ip>` on the office network. nginx serves the
app and passes `/api` to the backend; the backend is not exposed on its own port.
All data lives in `data/` inside the application folder:

```
/opt/kavach-platform/          <- the code you copied (example path)
├── docker-compose.prod.yml
├── .env                       <- secrets / settings (you create it)
└── data/
    ├── kavach.db              <- the database
    ├── uploads/               <- SIP, site survey, allotment files ...
    └── backups/
```

Replace `/opt/kavach-platform` below with the folder you copied the code to.

---

## 1. Install Docker (once)

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
curl -fsSL https://get.docker.com | sudo sh        # Docker Engine + Compose plugin
sudo usermod -aG docker $USER                      # then log out and back in
docker compose version                             # should print v2.x or later
```

The server needs internet access to Docker Hub, PyPI and npm for the first
build. If it has none, see "No internet on the server" at the end.

## 2. Fix Windows line endings (code copied from a Windows PC)

```bash
cd /opt/kavach-platform
sudo apt-get install -y dos2unix
find . -path ./frontend/node_modules -prune -o -type f \
     \( -name '*.sh' -o -name 'Dockerfile' -o -name '*.conf' -o -name '*.yml' -o -name '.env*' \) \
     -print0 | xargs -0 dos2unix
chmod +x deploy/backup.sh
```

You can delete `frontend/node_modules` and `frontend/dist` if you copied them
(they are Windows builds and are not used; the image builds its own).

## 3. Copy your current data from the PC

On the PC, **stop the local backend first** (Ctrl+C in its window) so the
database file is complete. Then, from PowerShell in `D:\2026\Applications\kavach-platform`:

```powershell
scp backend\kavach.db  <user>@<server-ip>:/opt/kavach-platform/data/kavach.db
scp -r backend\uploads <user>@<server-ip>:/opt/kavach-platform/data/
```

(Or copy them with WinSCP into `data/`.) On the server:

```bash
cd /opt/kavach-platform
mkdir -p data/uploads data/backups
ls -l data/ data/uploads        # kavach.db and the station_* folders should be there
```

Users, passwords, stations (Aler, Aler-PBP-IB ...), the allotment chart,
workspaces, checklist rules and deviations all come across in `kavach.db`.

## 4. Settings

```bash
cp .env.example .env
sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
nano .env        # optional: HTTP_PORT (default 80), SMTP_* for e-mail
```

`JWT_SECRET` signs login sessions. Keep it secret and do not change it later
(changing it just logs everyone out). If port 80 is already used on the server,
set e.g. `HTTP_PORT=8080` and open `http://<server-ip>:8080`.

## 5. Build and start

```bash
cd /opt/kavach-platform
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps          # both services "running"; backend "healthy"
curl -s http://localhost/api/health                    # {"status":"ok"}
```

The first build takes a few minutes. Both containers restart automatically
after a reboot or a crash (`restart: unless-stopped`).

Open the firewall if `ufw` is enabled:

```bash
sudo ufw allow 80/tcp        # or your HTTP_PORT
```

Now open `http://<server-ip>` from a PC on the network and log in with your
existing users.

## 6. Backups (recommended)

```bash
./deploy/backup.sh                         # test it once
crontab -e                                 # add the line below
30 1 * * *  cd /opt/kavach-platform && ./deploy/backup.sh >> data/backups/backup.log 2>&1
```

Nightly copies of the database and the uploads, kept for 14 days, in
`data/backups/`. Copy that folder off the server from time to time.

Restore: stop the app, put a backup in place, start again:

```bash
docker compose -f docker-compose.prod.yml down
cp data/backups/kavach-YYYYMMDD-HHMMSS.db data/kavach.db
tar -xzf data/backups/uploads-YYYYMMDD-HHMMSS.tar.gz -C data
docker compose -f docker-compose.prod.yml up -d
```

## Everyday commands

| What | Command (in `/opt/kavach-platform`) |
|---|---|
| Status | `docker compose -f docker-compose.prod.yml ps` |
| Backend logs | `docker compose -f docker-compose.prod.yml logs -f backend` |
| Web / nginx logs | `docker compose -f docker-compose.prod.yml logs -f web` |
| Restart | `docker compose -f docker-compose.prod.yml restart` |
| Stop | `docker compose -f docker-compose.prod.yml down` (data in `data/` is kept) |
| Reset a password | `docker compose -f docker-compose.prod.yml exec backend python scripts/reset_password.py --username <user> --password '<new password>'` |

## Updating to a new version of the code

1. Take a backup: `./deploy/backup.sh`
2. Copy the new code over the old folder, **keeping `data/` and `.env`**
   (don't copy `backend/kavach.db` or `backend/uploads` from the PC again unless
   you mean to replace the server's data).
3. Rebuild and restart:
   `docker compose -f docker-compose.prod.yml up -d --build`

Database changes (new tables / columns) are applied automatically when the
backend starts.

## Troubleshooting

- **Login page says it cannot reach the server** -- `docker compose ... ps`: is
  `backend` healthy? Check `logs backend`.
- **"413 Request Entity Too Large" on upload** -- files over 60 MB; raise
  `client_max_body_size` in `frontend/nginx.conf` and `MAX_UPLOAD_MB` in `.env`,
  then rebuild.
- **Downloads of old uploaded files fail with "missing from UPLOAD_DIR"** -- the
  `backend\uploads` folder from the PC was not copied into `data/uploads`.
- **Port already in use** -- set `HTTP_PORT` in `.env`, then
  `docker compose -f docker-compose.prod.yml up -d`.

## No internet on the server

Build the images on a machine with internet (and Docker), then move them:

```bash
# on the build machine, in the code folder
docker compose -f docker-compose.prod.yml build
docker save kavach-platform-backend kavach-platform-web | gzip > kavach-images.tar.gz
# copy kavach-images.tar.gz to the server, then there:
gunzip -c kavach-images.tar.gz | docker load
docker compose -f docker-compose.prod.yml up -d          # (no --build)
```

The image names follow the folder name (`<folder>-backend`, `<folder>-web`);
use the same folder name on both machines, or check `docker images`.

## Later: domain name and HTTPS

When a DNS name points at the server, put a TLS certificate in front (e.g. set
`HTTP_PORT=8080` and run Caddy or nginx with Let's Encrypt on 443 proxying to
`http://127.0.0.1:8080`). The app itself needs no change for this.
