# Bitget Trading Bot - Terraform Configuration for DigitalOcean
#
# This configuration creates:
# - VPC for network isolation
# - Droplet for the application
# - Firewall rules
# - DNS records (optional)
# - Spaces bucket for backups (optional)
#
# Usage:
#   cd terraform
#   terraform init
#   terraform plan -var="do_token=your_token"
#   terraform apply -var="do_token=your_token"

terraform {
  required_version = ">= 1.0.0"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.34"
    }
  }

  # Optional: Remote state storage
  # backend "s3" {
  #   endpoint                    = "nyc3.digitaloceanspaces.com"
  #   region                      = "us-east-1"
  #   bucket                      = "your-terraform-state"
  #   key                         = "bitget-trading-bot/terraform.tfstate"
  #   skip_credentials_validation = true
  #   skip_metadata_api_check     = true
  # }
}

provider "digitalocean" {
  token = var.do_token
}

# =============================================================================
# VARIABLES
# =============================================================================

variable "do_token" {
  description = "DigitalOcean API token"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "DigitalOcean region"
  type        = string
  default     = "nyc3"
}

variable "droplet_size" {
  description = "Droplet size"
  type        = string
  default     = "s-2vcpu-4gb" # $24/month - good for trading bot
}

variable "domain_name" {
  description = "Domain name for the application (optional)"
  type        = string
  default     = ""
}

variable "ssh_key_fingerprint" {
  description = "SSH key fingerprint for access"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "project_name" {
  description = "Project name for tagging"
  type        = string
  default     = "bitget-trading-bot"
}

# =============================================================================
# VPC
# =============================================================================

resource "digitalocean_vpc" "main" {
  name        = "${var.project_name}-vpc"
  region      = var.region
  description = "VPC for ${var.project_name}"
  ip_range    = "10.10.10.0/24"
}

# =============================================================================
# DROPLET
# =============================================================================

resource "digitalocean_droplet" "app" {
  name     = "${var.project_name}-${var.environment}"
  region   = var.region
  size     = var.droplet_size
  image    = "docker-20-04" # Docker pre-installed
  vpc_uuid = digitalocean_vpc.main.id

  ssh_keys = [var.ssh_key_fingerprint]

  tags = [
    var.project_name,
    var.environment,
    "docker",
    "trading-bot"
  ]

  # Cloud-init script for initial setup
  user_data = <<-EOF
    #!/bin/bash
    set -e

    # Update system
    apt-get update && apt-get upgrade -y

    # Install Docker Compose v2
    apt-get install -y docker-compose-plugin

    # Create app user
    useradd -m -s /bin/bash -G docker appuser

    # Create app directory
    mkdir -p /opt/bitget-trading-bot
    chown appuser:appuser /opt/bitget-trading-bot

    # Install fail2ban for security
    apt-get install -y fail2ban
    systemctl enable fail2ban
    systemctl start fail2ban

    # Configure unattended upgrades
    apt-get install -y unattended-upgrades
    dpkg-reconfigure -f noninteractive unattended-upgrades

    # Set up firewall (UFW)
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow http
    ufw allow https
    ufw --force enable

    # Create swap file (for small instances)
    if [ ! -f /swapfile ]; then
      fallocate -l 2G /swapfile
      chmod 600 /swapfile
      mkswap /swapfile
      swapon /swapfile
      echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi

    echo "Initial setup complete!"
  EOF

  lifecycle {
    create_before_destroy = true
  }
}

# =============================================================================
# FIREWALL
# =============================================================================

resource "digitalocean_firewall" "app" {
  name = "${var.project_name}-firewall"

  droplet_ids = [digitalocean_droplet.app.id]

  # Inbound rules
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0", "::/0"] # Consider restricting to your IP
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "icmp"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  # Outbound rules (allow all)
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}

# =============================================================================
# DNS (Optional - only if domain_name is set)
# =============================================================================

resource "digitalocean_domain" "main" {
  count = var.domain_name != "" ? 1 : 0
  name  = var.domain_name
}

resource "digitalocean_record" "app" {
  count  = var.domain_name != "" ? 1 : 0
  domain = digitalocean_domain.main[0].id
  type   = "A"
  name   = "@"
  value  = digitalocean_droplet.app.ipv4_address
  ttl    = 300
}

resource "digitalocean_record" "app_www" {
  count  = var.domain_name != "" ? 1 : 0
  domain = digitalocean_domain.main[0].id
  type   = "A"
  name   = "www"
  value  = digitalocean_droplet.app.ipv4_address
  ttl    = 300
}

resource "digitalocean_record" "app_api" {
  count  = var.domain_name != "" ? 1 : 0
  domain = digitalocean_domain.main[0].id
  type   = "A"
  name   = "api"
  value  = digitalocean_droplet.app.ipv4_address
  ttl    = 300
}

# =============================================================================
# SPACES BUCKET (Optional - for backups)
# =============================================================================

resource "digitalocean_spaces_bucket" "backups" {
  count  = var.domain_name != "" ? 1 : 0 # Only create if domain is set
  name   = "${var.project_name}-backups"
  region = var.region
  acl    = "private"

  lifecycle_rule {
    enabled = true

    expiration {
      days = 30 # Keep backups for 30 days
    }
  }
}

# =============================================================================
# PROJECT
# =============================================================================

resource "digitalocean_project" "main" {
  name        = var.project_name
  description = "Bitget Trading Bot - Automated cryptocurrency trading"
  purpose     = "Web Application"
  environment = var.environment == "production" ? "Production" : "Development"

  resources = [
    digitalocean_droplet.app.urn
  ]
}

# =============================================================================
# OUTPUTS
# =============================================================================

output "droplet_ip" {
  description = "Public IP address of the droplet"
  value       = digitalocean_droplet.app.ipv4_address
}

output "droplet_id" {
  description = "Droplet ID"
  value       = digitalocean_droplet.app.id
}

output "vpc_id" {
  description = "VPC ID"
  value       = digitalocean_vpc.main.id
}

output "ssh_command" {
  description = "SSH command to connect"
  value       = "ssh root@${digitalocean_droplet.app.ipv4_address}"
}

output "app_url" {
  description = "Application URL"
  value       = var.domain_name != "" ? "https://${var.domain_name}" : "http://${digitalocean_droplet.app.ipv4_address}"
}

output "deployment_instructions" {
  description = "Next steps for deployment"
  value       = <<-EOT

    Deployment Instructions:
    ========================

    1. SSH into the server:
       ssh root@${digitalocean_droplet.app.ipv4_address}

    2. Clone the repository:
       cd /opt/bitget-trading-bot
       git clone https://github.com/your-repo/bitget-trading-bot.git .

    3. Create .env file:
       cp .env.example .env
       nano .env  # Configure all secrets

    4. Start with Docker Compose:
       docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

    5. Check status:
       docker compose ps
       curl http://localhost/api/health

  EOT
}
