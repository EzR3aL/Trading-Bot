# Bitget Trading Bot - Terraform Variables
#
# Copy terraform.tfvars.example to terraform.tfvars and fill in your values

variable "do_token" {
  description = "DigitalOcean API token. Get one at: https://cloud.digitalocean.com/account/api/tokens"
  type        = string
  sensitive   = true
}

variable "ssh_key_fingerprint" {
  description = "SSH key fingerprint for server access. Find it at: https://cloud.digitalocean.com/account/security"
  type        = string
}

variable "region" {
  description = "DigitalOcean region (nyc1, nyc3, sfo3, ams3, lon1, fra1, sgp1, etc.)"
  type        = string
  default     = "nyc3"

  validation {
    condition     = contains(["nyc1", "nyc3", "sfo3", "ams3", "lon1", "fra1", "sgp1", "blr1", "tor1", "syd1"], var.region)
    error_message = "Invalid region. Choose from: nyc1, nyc3, sfo3, ams3, lon1, fra1, sgp1, blr1, tor1, syd1"
  }
}

variable "droplet_size" {
  description = "Droplet size. See: https://slugs.do-api.dev/"
  type        = string
  default     = "s-2vcpu-4gb"

  validation {
    condition = contains([
      "s-1vcpu-1gb",    # $6/month - testing only
      "s-1vcpu-2gb",    # $12/month - minimal
      "s-2vcpu-2gb",    # $18/month - basic
      "s-2vcpu-4gb",    # $24/month - recommended
      "s-4vcpu-8gb",    # $48/month - high performance
    ], var.droplet_size)
    error_message = "Invalid droplet size. Recommended: s-2vcpu-4gb ($24/month)"
  }
}

variable "domain_name" {
  description = "Domain name for the application (leave empty if not using custom domain)"
  type        = string
  default     = ""
}

variable "environment" {
  description = "Environment (production, staging, development)"
  type        = string
  default     = "production"

  validation {
    condition     = contains(["production", "staging", "development"], var.environment)
    error_message = "Environment must be: production, staging, or development"
  }
}

variable "project_name" {
  description = "Project name for resource naming and tagging"
  type        = string
  default     = "bitget-trading-bot"
}

variable "enable_monitoring" {
  description = "Enable DigitalOcean monitoring agent"
  type        = bool
  default     = true
}

variable "enable_backups" {
  description = "Enable weekly Droplet backups (+20% cost)"
  type        = bool
  default     = true
}
