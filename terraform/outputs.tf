# Bitget Trading Bot - Terraform Outputs

output "droplet_ip" {
  description = "Public IP address of the droplet"
  value       = digitalocean_droplet.app.ipv4_address
}

output "droplet_ipv6" {
  description = "IPv6 address of the droplet"
  value       = digitalocean_droplet.app.ipv6_address
}

output "droplet_id" {
  description = "Droplet ID"
  value       = digitalocean_droplet.app.id
}

output "droplet_urn" {
  description = "Droplet URN"
  value       = digitalocean_droplet.app.urn
}

output "vpc_id" {
  description = "VPC ID"
  value       = digitalocean_vpc.main.id
}

output "vpc_ip_range" {
  description = "VPC IP range"
  value       = digitalocean_vpc.main.ip_range
}

output "firewall_id" {
  description = "Firewall ID"
  value       = digitalocean_firewall.app.id
}

output "ssh_command" {
  description = "SSH command to connect to the server"
  value       = "ssh root@${digitalocean_droplet.app.ipv4_address}"
}

output "app_url" {
  description = "Application URL"
  value       = var.domain_name != "" ? "https://${var.domain_name}" : "http://${digitalocean_droplet.app.ipv4_address}"
}

output "api_url" {
  description = "API URL"
  value       = var.domain_name != "" ? "https://api.${var.domain_name}" : "http://${digitalocean_droplet.app.ipv4_address}/api"
}

output "domain_configured" {
  description = "Whether a domain is configured"
  value       = var.domain_name != ""
}

output "monthly_cost_estimate" {
  description = "Estimated monthly cost"
  value       = "~$${var.droplet_size == "s-1vcpu-1gb" ? "6" : var.droplet_size == "s-1vcpu-2gb" ? "12" : var.droplet_size == "s-2vcpu-2gb" ? "18" : var.droplet_size == "s-2vcpu-4gb" ? "24" : "48"}/month"
}
