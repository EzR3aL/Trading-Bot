#!/bin/bash
# Bitget Trading Bot - Traefik Deployment Script
#
# Usage: ./scripts/deploy-traefik.sh [--staging]
#
# This script deploys the trading bot with Traefik reverse proxy
# and automatic SSL via Let's Encrypt.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="docker-compose.yml"
TRAEFIK_COMPOSE="docker-compose.traefik.yml"

# Logging functions
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check required environment variables
check_env() {
    log_info "Checking environment variables..."

    local missing=0

    if [[ -z "${DOMAIN:-}" ]]; then
        log_error "DOMAIN environment variable is required"
        missing=1
    fi

    if [[ -z "${ACME_EMAIL:-}" ]]; then
        log_error "ACME_EMAIL environment variable is required"
        missing=1
    fi

    if [[ -z "${BITGET_API_KEY:-}" ]]; then
        log_warning "BITGET_API_KEY not set - trading will not work"
    fi

    if [[ $missing -eq 1 ]]; then
        log_error "Please set required environment variables in .env file"
        exit 1
    fi

    log_success "Environment variables OK"
}

# Create required directories
create_dirs() {
    log_info "Creating required directories..."

    mkdir -p "$PROJECT_DIR/traefik/acme"
    chmod 600 "$PROJECT_DIR/traefik/acme" 2>/dev/null || true

    log_success "Directories created"
}

# Create external network
create_network() {
    log_info "Creating external network..."

    if ! docker network inspect traefik-public >/dev/null 2>&1; then
        docker network create traefik-public
        log_success "Network 'traefik-public' created"
    else
        log_info "Network 'traefik-public' already exists"
    fi
}

# Build frontend
build_frontend() {
    log_info "Building frontend..."

    cd "$PROJECT_DIR/frontend"

    if [[ -f "package-lock.json" ]]; then
        npm ci
    else
        npm install
    fi

    npm run build

    cd "$PROJECT_DIR"
    log_success "Frontend built successfully"
}

# Generate htpasswd for Traefik dashboard
generate_dashboard_auth() {
    log_info "Generating Traefik dashboard authentication..."

    if [[ -z "${TRAEFIK_DASHBOARD_PASSWORD:-}" ]]; then
        TRAEFIK_DASHBOARD_PASSWORD=$(openssl rand -base64 12)
        log_warning "Generated random dashboard password: $TRAEFIK_DASHBOARD_PASSWORD"
        log_warning "Please save this password securely!"
    fi

    # Generate htpasswd entry
    if command -v htpasswd >/dev/null 2>&1; then
        HTPASSWD=$(htpasswd -nb admin "$TRAEFIK_DASHBOARD_PASSWORD")
    else
        # Use Docker if htpasswd not available
        HTPASSWD=$(docker run --rm httpd:alpine htpasswd -nb admin "$TRAEFIK_DASHBOARD_PASSWORD")
    fi

    # Update middlewares.yml with the new password
    sed -i "s|admin:\\\$apr1\\\$.*|${HTPASSWD//|/\\|}|" "$PROJECT_DIR/traefik/dynamic/middlewares.yml"

    log_success "Dashboard authentication configured"
}

# Deploy with Docker Compose
deploy() {
    log_info "Deploying services..."

    cd "$PROJECT_DIR"

    # Pull latest images
    docker compose -f "$COMPOSE_FILE" -f "$TRAEFIK_COMPOSE" pull

    # Build and start services
    docker compose -f "$COMPOSE_FILE" -f "$TRAEFIK_COMPOSE" up -d --build

    log_success "Services deployed"
}

# Wait for services to be healthy
wait_for_health() {
    log_info "Waiting for services to be healthy..."

    local max_attempts=30
    local attempt=0

    while [[ $attempt -lt $max_attempts ]]; do
        if docker compose -f "$COMPOSE_FILE" -f "$TRAEFIK_COMPOSE" ps | grep -q "healthy"; then
            log_success "Services are healthy"
            return 0
        fi

        attempt=$((attempt + 1))
        log_info "Waiting... ($attempt/$max_attempts)"
        sleep 10
    done

    log_warning "Some services may not be healthy yet"
}

# Show deployment status
show_status() {
    log_info "Deployment Status:"
    echo ""

    docker compose -f "$COMPOSE_FILE" -f "$TRAEFIK_COMPOSE" ps

    echo ""
    log_info "Access URLs:"
    echo "  - Application: https://${DOMAIN}"
    echo "  - API: https://${DOMAIN}/api"
    echo "  - Traefik Dashboard: https://traefik.${DOMAIN}"
    echo ""

    log_info "To view logs:"
    echo "  docker compose -f docker-compose.yml -f docker-compose.traefik.yml logs -f"
}

# Main function
main() {
    log_info "Starting Bitget Trading Bot deployment with Traefik..."
    echo ""

    # Parse arguments
    USE_STAGING=false
    while [[ $# -gt 0 ]]; do
        case $1 in
            --staging)
                USE_STAGING=true
                log_warning "Using Let's Encrypt staging server (for testing)"
                shift
                ;;
            *)
                log_error "Unknown argument: $1"
                exit 1
                ;;
        esac
    done

    # Load .env file if it exists
    if [[ -f "$PROJECT_DIR/.env" ]]; then
        set -a
        source "$PROJECT_DIR/.env"
        set +a
    fi

    # Run deployment steps
    check_env
    create_dirs
    create_network
    build_frontend
    generate_dashboard_auth
    deploy
    wait_for_health
    show_status

    log_success "Deployment complete!"
}

# Run main function
main "$@"
