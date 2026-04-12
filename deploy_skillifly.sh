#!/bin/bash

set -e

PROJECT_DIR="/var/www/skillifly/skillifly"
WEB_USER="www-data"

echo "🚀 Starting production setup for Skillifly..."

# Create required directories
mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$PROJECT_DIR/media"
mkdir -p "$PROJECT_DIR/staticfiles"

# Set ownership ONLY for writable directories
echo "Setting secure permissions..."

sudo chown -R $WEB_USER:$WEB_USER "$PROJECT_DIR/logs"
sudo chown -R $WEB_USER:$WEB_USER "$PROJECT_DIR/media"
sudo chown -R $WEB_USER:$WEB_USER "$PROJECT_DIR/staticfiles"

# Set permissions
sudo chmod -R 775 "$PROJECT_DIR/logs"
sudo chmod -R 775 "$PROJECT_DIR/media"
sudo chmod -R 775 "$PROJECT_DIR/staticfiles"

# SQLite (only if used)
if [ -f "$PROJECT_DIR/db.sqlite3" ]; then
    sudo chown $WEB_USER:$WEB_USER "$PROJECT_DIR/db.sqlite3"
    sudo chmod 664 "$PROJECT_DIR/db.sqlite3"
fi

echo "✅ Secure permissions applied."
