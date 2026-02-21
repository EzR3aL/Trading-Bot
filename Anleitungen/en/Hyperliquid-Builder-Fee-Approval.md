# Hyperliquid Builder Fee Approval

## What is the Builder Fee?

The Builder Fee is a small additional fee (0.01%) on every trade executed through
our bots on Hyperliquid. This fee goes 100% to the bot operator and is **in addition**
to the standard Hyperliquid trading fee.

You must approve this fee **once** before you can start a Hyperliquid bot.
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

Create a new bot with Hyperliquid as the exchange, or click "Start" on an
existing Hyperliquid bot.

If the Builder Fee has not yet been approved, the
**Builder Fee Approval window** will open automatically.

### 2. Connect Wallet

Click on **"Connect Wallet"** -- a selection window will open with
all supported wallets:

- **MetaMask** (Browser extension)
- **WalletConnect** (QR code for mobile wallets like Trust, Rainbow, etc.)
- **Coinbase Wallet**
- **And many more...**

Select your wallet and confirm the connection.

> **Important:** Connect the same wallet address that you entered as your Hyperliquid
> Main Wallet in the exchange settings!
> If the addresses do not match, a warning will be displayed.

### 3. Sign the Builder Fee

After connecting your wallet, you will see the Builder Fee details:
- **Fee**: 0.01% (1 basis point) per trade
- **Builder address**: The bot operator's address

Click on **"Approve Builder Fee"**. Your wallet will open and display
the signature request. This is an **EIP-712 Typed Data Signature** -- no
transactions are executed and no funds are moved.

Confirm the signature in your wallet.

### 4. Confirmation

After a successful signature, the approval is automatically verified with Hyperliquid
and saved in your account. You will see a green checkmark
with the message **"Builder Fee approved!"**.

The bot will then start automatically.

---

## Common Issues

### "Connected wallet does not match..."
You connected a different wallet than your Hyperliquid Main Wallet.
Switch to the correct address in your wallet extension.

### "Signature failed"
The signature was rejected in the wallet. Try again and confirm
the signature request.

### "Verification failed"
The signature was created but could not be verified with Hyperliquid.
Possible causes:
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
4. Return to the bot dashboard and restart the approval process
