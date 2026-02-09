# Hyperliquid Revenue: Builder Code & Referral

This document explains how the Trading Bot earns revenue from Hyperliquid trades via **Builder Codes** and **Referral/Affiliate** programs.

---

## 1. Builder Code (Per-Order Fee)

### What It Is

A Builder Code adds a small fee to every Hyperliquid order the bot places. The fee is **additional** to the exchange fee and goes **100% to the builder** (you). There is no cap on earnings.

### Fee Structure

| HL_BUILDER_FEE | Basis Points | Percentage | Per $10,000 Trade |
|----------------|-------------|------------|-------------------|
| 1              | 0.1 bp      | 0.001%     | $0.10             |
| **10 (default)** | **1.0 bp** | **0.01%**  | **$1.00**         |
| 50             | 5.0 bp      | 0.05%      | $5.00             |
| 100 (max perps)| 10.0 bp     | 0.10%      | $10.00            |

### Setup

1. **Fund your builder wallet**: Your builder address must hold >= 100 USDC in its perps account on Hyperliquid.

2. **Configure `.env`**:
   ```bash
   # Your wallet address (the one receiving builder fees)
   HL_BUILDER_ADDRESS=0xYourWalletAddress

   # Fee in tenths of basis points (1-100)
   HL_BUILDER_FEE=10
   ```

3. **Restart the backend** for changes to take effect.

4. **User approval**: Each user must approve the builder fee once. This happens via an EIP-712 signed message. Two ways to approve:
   - **Automatic**: The bot checks approval status when starting. If not approved, a warning is logged.
   - **Manual**: Go to **Settings > Hyperliquid** tab and click "Approve Builder Fee".
   - **API**: `POST /api/config/hyperliquid/approve-builder-fee`

### How It Works Technically

1. On startup, `HyperliquidClient.__init__()` reads `HL_BUILDER_ADDRESS` and `HL_BUILDER_FEE` from environment.
2. If valid, it creates `self._builder = {"b": "0xaddr", "f": fee}`.
3. Every `market_open()`, `market_close()`, and trigger `order()` call includes `builder=self._builder` as a parameter to the SDK.
4. The SDK includes the builder field in the EIP-712 signed action hash.
5. Hyperliquid deducts the builder fee from the user's account and credits the builder wallet.

### Checking Status

- **API**: `GET /api/config/hyperliquid/builder-status`
- **Frontend**: Settings > Hyperliquid tab shows builder address, fee rate, and approval status.
- **Logs**: Look for `"Builder code enabled: 0xAddr... fee=10 (1.0 bp = 0.010%)"` on startup.

### Changing the Fee

1. Update `HL_BUILDER_FEE` in `.env`
2. Restart the backend
3. **Important**: If the new fee is higher than what users previously approved, they must re-approve. The bot will log a warning about partial approval.

### Disabling Builder Code

Remove or empty `HL_BUILDER_ADDRESS` in `.env` and restart. Orders will be placed without builder fees.

---

## 2. Referral / Affiliate Program

### What It Is

Hyperliquid's referral program gives you **10% of referred users' trading fees** (capped at $1B volume per user). This is separate from and stacks with builder fees.

### Setup

1. **Create a referral code** at [app.hyperliquid.xyz/referrals](https://app.hyperliquid.xyz/referrals)
   - Requires >= $10K trading volume on your account.

2. **Configure `.env`**:
   ```bash
   # Your referral code (shown on the referrals page)
   HL_REFERRAL_CODE=YOURCODE

   # Optional: Require users to register via referral before using HL bots
   HL_REQUIRE_REFERRAL=false
   ```

3. **Restart the backend**.

### Referral Gate (Optional)

When `HL_REQUIRE_REFERRAL=true`:
- Before starting a Hyperliquid bot, the system checks if the user has been referred.
- If not referred, the bot shows an error with the referral link: `https://app.hyperliquid.xyz/join/YOURCODE`
- The user must visit the link and complete registration before the bot will start.

**Limitation**: The `setReferrer` action requires the user's **main wallet** signature (not the API wallet). The bot cannot automatically set the referrer — the user must do it manually via the Hyperliquid website.

### Checking Status

- **API**: `GET /api/config/hyperliquid/referral-status`
- **Frontend**: Settings > Hyperliquid tab shows referral code and whether the user is referred.

---

## 3. Revenue Dashboard

### API Endpoint

`GET /api/config/hyperliquid/revenue-summary` returns a combined overview:

```json
{
  "builder": {
    "configured": true,
    "address": "0xAbCdEf12...",
    "fee_rate": 10,
    "fee_percent": "0.010%",
    "user_approved": true
  },
  "referral": {
    "configured": true,
    "code": "YOURCODE",
    "user_referred": false,
    "link": "https://app.hyperliquid.xyz/join/YOURCODE"
  },
  "user_fees": { ... }
}
```

### Frontend

Navigate to **Settings > Hyperliquid** tab to see:
- Builder Code status (address, fee, approval)
- Referral status (code, whether user is referred)
- User fee tier information

---

## 4. Revenue Stacking

Both revenue streams are **independent and complementary**:

| Revenue Stream   | Source             | Rate                  | Cap           |
|-----------------|--------------------|-----------------------|---------------|
| Builder Code    | Per-order fee      | 0.01% (configurable)  | No cap        |
| Referral        | 10% of user fees   | ~0.0035% of volume    | $1B vol/user  |

**Example**: A user trading $100K/day:
- Builder fee (0.01%): $10/day
- Referral (10% of ~0.035% fees): ~$3.50/day
- **Combined**: ~$13.50/day per active user

---

## 5. Troubleshooting

| Issue | Solution |
|-------|----------|
| "Builder code disabled" in logs | Check `HL_BUILDER_ADDRESS` is set and `HL_BUILDER_FEE` is 1-100 |
| "Builder fee NOT approved" warning | User needs to approve via Settings > Hyperliquid or API |
| Orders fail with builder fee error | Fee exceeds user's approved max — ask user to re-approve |
| "Referral required" error on bot start | User must register via referral link first |
| Builder wallet doesn't receive fees | Ensure builder wallet has >= 100 USDC in perps account |

---

## 6. Files Reference

| File | Purpose |
|------|---------|
| `src/exchanges/hyperliquid/client.py` | Builder injection into orders, approval check, referral query |
| `src/exchanges/hyperliquid/constants.py` | `DEFAULT_BUILDER_FEE = 10` |
| `src/api/routers/config.py` | API endpoints for builder/referral status |
| `src/bot/bot_worker.py` | Pre-start checks (approval, referral gate) |
| `frontend/src/pages/Settings.tsx` | Hyperliquid revenue dashboard tab |
| `.env.example` | Configuration reference |
| `tests/unit/exchanges/test_hyperliquid_builder.py` | 25 unit tests |
