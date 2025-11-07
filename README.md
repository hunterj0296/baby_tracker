# Baby Tracker (Raspberry Pi 5)

Lightweight LAN webapp to log feeds, poops, and pees; see last 24h status vs age-adjusted targets. Runs in Docker, persists to SQLite on SSD.

## Requirements
- Raspberry Pi 5 (64-bit OS)
- Docker & Docker Compose

## Configure
- Defaults (can be changed in `docker-compose.yml`):
  - `DAY_ZERO=2025-10-28` (birth date; no targets until Day 1)
  - `DATA_PATH=/data/baby_tracking.db`
  - `RATE_LIMIT=60/min`
  - `TZ=UTC`

## Build & Run
```bash
# On your Pi in this folder
docker compose build
mkdir -p data
docker compose up -d
# Browse on your phone while on the same LAN:
# http://<pi-ip>:8080
```

## Usage
- Home shows quick buttons. Each form defaults to now (editable).
- Feed amounts support oz/mL toggle; both units are stored for each entry.
- Status shows:
  - Feeds: count, total, average per feed and target range
  - Pees: count (target ≥ 6)
  - Poops: time since last (yellow > 24h, red > 48h)

## Backup
- The SQLite database is stored at `./data/baby_tracking.db` on the host. Back it up regularly.

## Notes
- All times are stored in UTC and displayed using your device locale.
- Endpoints are rate-limited per-client IP.

