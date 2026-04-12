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
