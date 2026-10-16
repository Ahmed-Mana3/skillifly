# Deployment Guide: Skillifly Backend (Ubuntu VPS)

This guide walks you through deploying Skillifly on an **Ubuntu VPS** using **Nginx**, **Gunicorn**, and **SQLite**.

## 1. System Preparation

Update your system and install necessary packages:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv nginx redis-server certbot python3-certbot-nginx -y
```

## 2. Project Setup

Clone your repository:
```bash
cd /var/www
sudo git clone https://github.com/Ahmed-Mana3/skillifly.git skillifly
sudo chown -R $USER:$USER /var/www/skillifly
cd /var/www/skillifly
```

Create a virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. Environment Variables

Create your production `.env` file:
```bash
cp .env.example .env
nano .env
```
**Required Changes:**
- `DJANGO_DEBUG=False`
- `DJANGO_SECRET_KEY=` (Generate one with `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`)
- `DJANGO_ALLOWED_HOSTS=skillifly.cloud,www.skillifly.cloud`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://skillifly.cloud,https://www.skillifly.cloud`

## 4. Run Initial Django Commands

```bash
python manage.py collectstatic --noinput
python manage.py migrate
```

## 5. Deployment Setup (Gunicorn & Systemd)

### Create Gunicorn Socket
`sudo nano /etc/systemd/system/skillifly.socket`
```ini
[Unit]
Description=gunicorn socket

[Socket]
ListenStream=/run/skillifly.sock

[Install]
WantedBy=sockets.target
```

### Create Gunicorn Service
`sudo nano /etc/systemd/system/skillifly.service`
```ini
[Unit]
Description=gunicorn daemon
Requires=skillifly.socket
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/skillifly/skillifly
ExecStart=/var/www/skillifly/skillifly/venv/bin/gunicorn \
          --access-logfile - \
          --workers 3 \
          --bind unix:/run/skillifly.sock \
          skillifly.wsgi:application

[Install]
WantedBy=multi-user.target
```

## 6. Nginx Configuration

`sudo nano /etc/nginx/sites-available/skillifly`
```nginx
server {
    listen 80;
    server_name skillifly.cloud www.skillifly.cloud;

    location = /favicon.ico { access_log off; log_not_found off; }
    
    location /static/ {
        root /var/www/skillifly/skillifly;
    }

    location /media/ {
        root /var/www/skillifly/skillifly;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/run/skillifly.sock;
    }
}
```

Enable the site and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/skillifly /etc/nginx/sites-enabled
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable skillifly.socket
sudo systemctl start skillifly.socket
```

## 7. Folder Permissions (CRITICAL for SQLite)

Since SQLite writes to the folder itself, we must give `www-data` ownership of the project folder or at least the DB and media:
```bash
sudo chown -R www-data:www-data /var/www/skillifly/skillifly
sudo chmod -R 775 /var/www/skillifly/skillifly
```

## 8. SSL (HTTPS)

```bash
sudo certbot --nginx -d skillifly.cloud -d www.skillifly.cloud
```

## 9. Celery Worker (Background Tasks)

To run the Celery worker in production, you should create another systemd service similar to `skillifly.service` that runs:
`venv/bin/celery -A skillifly worker --loglevel=info`

## 10. Onboarding v2 (welcome flow, nudge emails)

Design and rollout notes live in `ONBOARDING_V2_PLAN.md`. Everything user-visible is behind
switches in **Admin -> Core -> Site Settings**, all **off by default**:

| Switch | Effect |
|---|---|
| `onboarding_v2_enabled` | New editors are sent to `/welcome/` (paste a video link), see a first-run dashboard, get the reveal bar and the short signup form |
| `defer_email_verification` | New editors are let in before entering the email code; the code is required to publish or pay |
| `nudges_enabled` | The hourly `send_onboarding_nudges` job sends emails (a dry run works either way) |
| `default_editor_theme` | Theme given to new editors (empty = Video Editor > Creative). Must not need a profile photo |

Migrate (the schema changes only add columns and tables), then restart gunicorn:
```bash
python manage.py migrate
sudo systemctl restart skillifly
```

### Nudge email timer
```bash
sudo cp deploy/systemd/skillifly-nudges.service deploy/systemd/skillifly-nudges.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now skillifly-nudges.timer
systemctl list-timers | grep skillifly        # next run
journalctl -u skillifly-nudges --since today  # what it sent
```
Preview what the next run would send without sending anything:
```bash
python manage.py send_onboarding_nudges --dry-run --ignore-quiet-hours
```
Before turning `nudges_enabled` on, check SPF / DKIM / DMARC for the sending domain and send a test
message to mail-tester.com. Emails are never sent between 22:00 and 09:00 Cairo time.

### Funnel report
```bash
python manage.py activation_report --since 2026-05-01 --until 2026-09-30 --stalled-csv logs/stalled.csv
python manage.py activation_report --since 2026-05-01 --until 2026-09-30 --compare-since <launch date>
```
The CSV contains email addresses: it is written under `logs/` (git-ignored) and must not be committed.

### Setting up a portfolio by hand for someone who replied with links
```bash
python manage.py add_concierge_projects <username> <video-url> [<video-url> ...] [--title "Brand film"] [--lang ar] [--dry-run]
```
Does what the welcome page does (lookup, thumbnail, default theme, personal info) but labels the projects
`source=concierge`, so `activation_report` shows them separately ("first project by source") and they don't
inflate real product activation. `--dry-run` looks the links up and creates nothing.

### Optional settings (`.env`)
`SITE_BASE_URL` (absolute URL used in emails), `NUDGE_FOUNDER_NAME` (name used in the personal
"quick question" email), `CLARITY_PROJECT_ID` (Microsoft Clarity session recordings on the signup,
dashboard, builder and welcome pages; form inputs are masked by default).

### Rollback
Untick `onboarding_v2_enabled` in Site Settings (no deploy needed) and `systemctl disable --now skillifly-nudges.timer`.
Created projects, personal info and themes are ordinary records and stay as they are.
