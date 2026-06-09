#!/usr/bin/env bash
# GCE Setup Script for arkfarms.store
# Execute this on your GCE VM to install dependencies and configure Nginx / SSL.

set -euo pipefail

EMAIL="aravindkasireddy5@gmail.com"
DOMAIN="arkfarms.store"
WWW_DOMAIN="www.arkfarms.store"

echo "=========================================="
echo "Starting GCE Setup for $DOMAIN"
echo "=========================================="

# 1. Update Package Registry
echo "Updating packages..."
sudo apt-get update -y

# 2. Install Git, Docker, Nginx, Certbot, and Python Nginx Certbot Plugin
echo "Installing dependencies..."
sudo apt-get install -y \
    git \
    curl \
    nginx \
    certbot \
    python3-certbot-nginx \
    docker.io \
    docker-compose

# 3. Start & Enable Docker
echo "Configuring Docker service..."
sudo systemctl start docker
sudo systemctl enable docker

# 4. Add current user to Docker group (so you don't need 'sudo' for docker commands)
if ! groups "$USER" | grep &>/dev/null '\bdocker\b'; then
    echo "Adding $USER to docker group. Note: You will need to log out and log back in for this to take effect."
    sudo usermod -aG docker "$USER"
fi

# 5. Copy Nginx config to site directory
echo "Configuring Nginx Reverse Proxy..."
if [ -f "deploy/nginx.conf" ]; then
    sudo cp deploy/nginx.conf /etc/nginx/sites-available/arkfarms.store
else
    echo "Error: deploy/nginx.conf not found. Please ensure you are running this script from the repository root."
    exit 1
fi

# Enable the Nginx site
sudo ln -sf /etc/nginx/sites-available/arkfarms.store /etc/nginx/sites-enabled/arkfarms.store

# Disable the default site if it exists to avoid port 80 collisions
sudo rm -f /etc/nginx/sites-enabled/default

# Test and reload Nginx config
echo "Testing Nginx configuration..."
sudo nginx -t
echo "Restarting Nginx..."
sudo systemctl restart nginx

# 6. Run Certbot for SSL Certificate Sourcing & Auto-Renewal
echo "Generating Let's Encrypt SSL Certificate..."
sudo certbot --nginx \
    -d "$DOMAIN" \
    -d "$WWW_DOMAIN" \
    --non-interactive \
    --agree-tos \
    --email "$EMAIL" \
    --redirect

echo "=========================================="
echo "GCE Setup Completed!"
echo "=========================================="
echo "Next Steps:"
echo "1. Run: cp .env.example .env"
echo "2. Edit the .env file with your production keys:"
echo "   - NEXT_PUBLIC_API_URL=https://arkfarms.store"
echo "   - OPENAI_API_KEY=..."
echo "   - GEMINI_API_KEY=..."
echo "   - SUPABASE_URL=..."
echo "   - SUPABASE_SERVICE_ROLE_KEY=..."
echo "3. Run: docker-compose up --build -d"
echo "=========================================="
