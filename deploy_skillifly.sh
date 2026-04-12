#!/bin/bash

# ============================================================
#  Skillifly Backend — Production Deployment Helper Script
#  Run this on your Ubuntu VPS to set up folder permissions.
# ============================================================

set -e

PROJECT_DIR="/var/www/skillifly/skillifly"
WEB_USER="www-data"

echo "🚀 Starting production setup for Skillifly..."

# 1. Ensure logs directory exists
if [ ! -d "$PROJECT_DIR/logs" ]; then
    echo "Creating logs directory..."
    mkdir -p "$PROJECT_DIR/logs"
fi

# 2. Ensure media and staticfiles directories exist
mkdir -p "$PROJECT_DIR/media"
mkdir -p "$PROJECT_DIR/staticfiles"

# 3. Set ownership to www-data for web-writable folders
echo "Setting permissions for folders and SQLite database..."
sudo chown -R $WEB_USER:$WEB_USER "$PROJECT_DIR"
sudo chmod -R 775 "$PROJECT_DIR"

# 4. Handle SQLite file specifically if it exists
if [ -f "$PROJECT_DIR/db.sqlite3" ]; then
    sudo chown $WEB_USER:$WEB_USER "$PROJECT_DIR/db.sqlite3"
    sudo chmod 664 "$PROJECT_DIR/db.sqlite3"
fi

echo "✅ Permissions updated successfully."
echo "Next steps:"
echo "1. Configure your .env file"
echo "2. Run 'source venv/bin/activate && python manage.py migrate'"
echo "3. Run 'python manage.py collectstatic'"
echo "4. Restart gunicorn: sudo systemctl restart skillifly"
