# SSL Certificate Setup

This directory should contain your SSL certificates:

- `fullchain.pem` - Full certificate chain
- `privkey.pem` - Private key

## Option 1: Let's Encrypt (Recommended for Production)

```bash
# Install certbot
apt-get install certbot python3-certbot-nginx

# Get certificate
certbot certonly --standalone -d your-domain.com

# Copy certificates
cp /etc/letsencrypt/live/your-domain.com/fullchain.pem nginx/ssl/
cp /etc/letsencrypt/live/your-domain.com/privkey.pem nginx/ssl/

# Auto-renewal is set up automatically by certbot
```

## Option 2: Self-Signed (Development/Testing Only)

```bash
# Generate self-signed certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/privkey.pem \
  -out nginx/ssl/fullchain.pem \
  -subj "/CN=localhost"
```

## Option 3: DigitalOcean Managed SSL

If using DigitalOcean App Platform or Load Balancer, SSL is managed automatically.

## Security Notes

- Never commit private keys to git
- Set proper file permissions: `chmod 600 privkey.pem`
- Rotate certificates before expiry
- Use strong key sizes (2048-bit minimum, 4096-bit recommended)
