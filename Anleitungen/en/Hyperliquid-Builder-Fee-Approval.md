# Hyperliquid: Affiliate Link & Builder Fee Approval

## Overview

Before you can start a Hyperliquid bot, **two one-time steps** are required:

1. **Use Affiliate Link** — Register on Hyperliquid via our referral link
2. **Approve Builder Fee** — Sign an approval for a small trading fee

Both steps are **one-time per wallet**. As long as you use the same wallet, you won't need to repeat them. If you change your wallet, both steps will be required again.

---

## What is the Affiliate Link?

The affiliate link is a referral link for registering on Hyperliquid. As a new user, you receive a **4% discount on trading fees** (for the first $25M in volume).

**Important:** Without registering via our affiliate link, you cannot start a Hyperliquid bot. Verification is done automatically via the Hyperliquid API.

## What is the Builder Fee?

The Builder Fee is a small additional fee (0.01%) on every trade executed through
our bots on Hyperliquid. This fee goes 100% to the bot operator and is **in addition**
to the standard Hyperliquid trading fee.

**No funds are moved or deducted** during this process -- it is only a signature (approval).

---

## Prerequisites

1. **Hyperliquid account** with API keys stored in the bot dashboard
2. **Browser wallet** (MetaMask, Coinbase Wallet, Rainbow, Trust Wallet, or others)
   with your **Hyperliquid Main Wallet** imported
3. Your Main Wallet is the wallet address that you entered as "API Key" (Wallet Address)
   in the exchange settings

---

## Step-by-Step Guide

### 1. Create or Start a Bot

Create a new bot with Hyperliquid as the exchange, or click **"Start"** on an
existing Hyperliquid bot.

The **approval window** will open automatically with the multi-step process.

### 2. Use Affiliate Link (Step 1 in the window)

You will see our affiliate link:
```
https://app.hyperliquid.xyz/join/YOURCODE
```

- Click the link — it opens in a new tab
- Register or log in to Hyperliquid
- Return to the bot dashboard
- Click **"Verify"**

Verification automatically checks via the Hyperliquid API whether you registered through our link.

> **Note:** If you are already registered via our link, this step is automatically skipped.

### 3. Connect Wallet (Step 2)

Click on **"Connect Wallet"** -- a selection window will open:

- **Rabby Wallet** (recommended — best UX for DeFi)
- **MetaMask** (Browser extension)
- **WalletConnect** (QR code for mobile wallets like Trust, Rainbow, etc.)
- **Coinbase Wallet**
- **And many more...**

Select your wallet and confirm the connection.

> **Important:** Connect the same wallet address that you entered as your Hyperliquid
> Main Wallet in the exchange settings!

### 4. Sign the Builder Fee (Step 3)

After connecting your wallet, you will see the details:
- **Fee**: 0.01% (1 basis point) per trade
- **Builder address**: The bot operator's address

Click on **"Approve Builder Fee"**. Your wallet will open and display
the signature request. This is an **EIP-712 Typed Data Signature** -- no
transactions are executed and no funds are moved.

Confirm the signature in your wallet.

### 5. Done! (Step 4)

After a successful signature, you will see a green checkmark with **"Builder Fee approved!"**.
The bot will then **start automatically**.

---

## Changing Your Wallet

If you change your Hyperliquid wallet address in the exchange settings, both approvals (affiliate + builder fee) are **automatically reset**. On the next bot start, you will need to go through the process again for the new wallet.

---

## Common Issues

### "Referral verification failed"
You did not register via our affiliate link, or your registration was done
through a different referral code.
- Open the affiliate link and register again
- Then click "Verify"

### "Connected wallet does not match..."
You connected a different wallet than your Hyperliquid Main Wallet.
Switch to the correct address in your wallet extension.

### "Signature failed"
The signature was rejected in the wallet. Try again and confirm
the signature request.

### "Verification failed"
The signature could not be verified with Hyperliquid. Possible causes:
- Wrong wallet address
- Network issues
Wait a moment and try again.

### No wallet installed?
Without a browser wallet, you can still use mobile wallets:
Select **WalletConnect** and scan the QR code with your mobile wallet app
(Trust Wallet, Rainbow, MetaMask Mobile, etc.).

### Installing MetaMask
1. Go to [metamask.io](https://metamask.io/download/)
2. Install the browser extension
3. Import your Hyperliquid wallet with the private key or seed phrase
4. Return to the bot dashboard and restart the process
