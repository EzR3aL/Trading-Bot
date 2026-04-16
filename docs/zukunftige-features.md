# Zukuenftige Features / Future Features

> **Letzte Aktualisierung:** 2026-04-16 (v4.14.x)

## Deutsch

### Uebersicht
Dieses Dokument beschreibt geplante Features fuer den Trading-Bot, die in zukuenftigen Versionen umgesetzt werden sollen.

---

### 1. Strategy Marketplace
- **Prioritaet:** Mittel
- **Aufwand:** XL
- **Status:** Offen
- **Beschreibung:** Ein Marktplatz, auf dem Benutzer eigene Trading-Strategien erstellen, teilen und verkaufen koennen. Andere Benutzer koennen diese Strategien abonnieren und direkt in ihrem Bot einsetzen. Der Marketplace soll ein Bewertungssystem und Performance-Statistiken enthalten.

### ~~2. Social/Copy Trading mit Leaderboard~~
- **Status:** TEILWEISE UMGESETZT (v4.16.0)
- **Was implementiert wurde:** Copy-Trading-Strategie (`copy_trading`), die eine oeffentliche Hyperliquid-Wallet trackt und Entries sowie Full-Closes auf eine beliebige Ziel-Exchange (Bitget, BingX, Bitunix, Weex, Hyperliquid) kopiert. Validierung der Source-Wallet, Whitelist/Blacklist, Slot-Limit, Leverage-Cap.
- **Was noch fehlt:** Leaderboard, Social-Komponente (Trader folgen/bewerten), Add-Ins und Teil-Closes spiegeln.

### 3. Native Mobile App (React Native)
- **Prioritaet:** Niedrig
- **Aufwand:** XXL
- **Status:** Offen
- **Beschreibung:** Eine native Mobile App fuer iOS und Android, entwickelt mit React Native. Die App soll alle wesentlichen Funktionen des Web-Dashboards bieten: Bot-Steuerung, Revenue-Dashboard, Benachrichtigungen (Push-Notifications) und Echtzeit-Monitoring der laufenden Bots.

---

## English

### Overview
This document describes planned features for the Trading Bot that are intended to be implemented in future versions.

---

### 1. Strategy Marketplace
- **Priority:** Medium
- **Effort:** XL
- **Status:** Open
- **Description:** A marketplace where users can create, share, and sell custom trading strategies. Other users can subscribe to these strategies and deploy them directly in their bot. The marketplace will include a rating system and performance statistics.

### ~~2. Social/Copy Trading with Leaderboard~~
- **Status:** PARTIALLY IMPLEMENTED (v4.16.0)
- **What was implemented:** Copy-trading strategy (`copy_trading`) that tracks a public Hyperliquid wallet and copies entries and full closes to any target exchange (Bitget, BingX, Bitunix, Weex, Hyperliquid). Source wallet validation, whitelist/blacklist, slot limit, leverage cap.
- **What is still missing:** Leaderboard, social component (follow/rate traders), add-ins and partial close mirroring.

### 3. Native Mobile App (React Native)
- **Priority:** Low
- **Effort:** XXL
- **Status:** Open
- **Description:** A native mobile app for iOS and Android, built with React Native. The app should provide all essential features of the web dashboard: bot control, revenue dashboard, notifications (push notifications), and real-time monitoring of running bots.
