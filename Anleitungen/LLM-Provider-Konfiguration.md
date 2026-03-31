# LLM-Provider Konfiguration

> **Hinweis (2026-03-26):** Die LLM-Integration wurde in Version 4.6.0 vollstaendig entfernt.
> Diese Anleitung ist nur noch als Archiv-Referenz vorhanden.
> Der Code ist unter dem Git-Tag `llm-archive-v4.5` archiviert.

~~Anleitung zur Einrichtung und Konfiguration der unterstuetzten LLM-Provider fuer die KI-Strategien (LLM Signal und Degen).~~

---

## Inhaltsverzeichnis

1. [Ueberblick](#1-ueberblick)
2. [Provider im Detail](#2-provider-im-detail)
3. [Konfiguration im Bot](#3-konfiguration-im-bot)
4. [Model-Auswahl und Empfehlungen](#4-model-auswahl-und-empfehlungen)
5. [Troubleshooting](#5-troubleshooting)

---

## 1. Ueberblick

Die Strategien **LLM Signal** und **Degen** nutzen externe KI-Modelle fuer die Signal-Generierung. Du brauchst mindestens einen API-Key von einem der folgenden Provider:

| Provider | Modelle | Geschwindigkeit | Kosten | Empfehlung |
|----------|---------|----------------|--------|------------|
| **OpenAI** | GPT-4.1, GPT-4.1 Mini | Mittel | Mittel | Beste Qualitaet |
| **Anthropic** | Claude Haiku 4.5 | Mittel | Mittel | Sehr gut fuer Analyse |
| **Gemini Flash** | Gemini 2.5 Flash | Schnell | Guenstig | Gutes Preis-Leistungs-Verhaeltnis |
| **Gemini Pro** | Gemini 3 Pro (Preview) | Mittel | Mittel | Bestes Google-Modell |
| **Groq** | Llama 4 Maverick | Sehr schnell | Guenstig | Schnellste Antworten |
| **Mistral** | Mistral Small 3.2 | Schnell | Guenstig | Europaeischer Provider |
| **xAI** | Grok 3 Mini | Mittel | Mittel | Echtzeit-Daten |
| **Perplexity** | Sonar | Schnell | Mittel | Internet-Zugang |
| **DeepSeek** | DeepSeek V3 Chat, DeepSeek Reasoner | Schnell | Sehr guenstig | Bestes Preis-Leistungs-Verhaeltnis |

---

## 2. Provider im Detail

### OpenAI

1. Gehe zu [platform.openai.com](https://platform.openai.com)
2. Erstelle einen Account oder melde dich an
3. Navigiere zu **API Keys** (linke Seite)
4. Klicke auf **"Create new secret key"**
5. Gib dem Key einen Namen (z.B. "Trading Bot")
6. Kopiere den Key (beginnt mit `sk-`)

**Wichtig:** Der Key wird nur einmal angezeigt! Speichere ihn sicher.

**Empfohlene Modelle:**
- `gpt-4.1` -- Beste Qualitaet, hoeherer Preis
- `gpt-4.1-mini` -- Guenstiger, fuer die meisten Faelle ausreichend (Standard)

### Anthropic

1. Gehe zu [console.anthropic.com](https://console.anthropic.com)
2. Erstelle einen Account
3. Navigiere zu **API Keys**
4. Klicke auf **"Create Key"**
5. Kopiere den Key (beginnt mit `sk-ant-`)

**Empfohlene Modelle:**
- `claude-haiku-4-5-20251001` -- Schnell und guenstig (Standard)

### Gemini (Google)

1. Gehe zu [aistudio.google.com](https://aistudio.google.com)
2. Melde dich mit deinem Google-Account an
3. Klicke auf **"Get API Key"**
4. Erstelle einen Key in einem neuen oder bestehenden Projekt
5. Kopiere den Key

**Empfohlene Modelle:**
- `gemini-3-pro-preview` -- Bestes Google-Modell (als `gemini_pro` Provider)
- `gemini-2.5-flash` -- Schneller, guenstiger (Standard fuer `gemini` Provider)

### Groq

1. Gehe zu [console.groq.com](https://console.groq.com)
2. Erstelle einen Account
3. Navigiere zu **API Keys**
4. Klicke auf **"Create API Key"**
5. Kopiere den Key (beginnt mit `gsk_`)

**Empfohlene Modelle:**
- `meta-llama/llama-4-maverick-17b-128e-instruct` -- Llama 4 Maverick (Standard)

**Besonderheit:** Groq bietet **extrem schnelle Inferenz** (oft < 1 Sekunde). Ideal fuer Echtzeit-Trading.

### Mistral

1. Gehe zu [console.mistral.ai](https://console.mistral.ai)
2. Erstelle einen Account
3. Navigiere zu **API Keys**
4. Klicke auf **"Create new key"**
5. Kopiere den Key

**Empfohlene Modelle:**
- `mistral-small-2506` -- Mistral Small 3.2 (Standard)

### xAI (Grok)

1. Gehe zu [console.x.ai](https://console.x.ai)
2. Melde dich an (X/Twitter Account erforderlich)
3. Navigiere zu **API Keys**
4. Erstelle einen neuen Key
5. Kopiere den Key

**Empfohlene Modelle:**
- `grok-3-mini` -- Grok 3 Mini (Standard)

### Perplexity

1. Gehe zu [docs.perplexity.ai](https://docs.perplexity.ai)
2. Erstelle einen Account
3. Navigiere zu **API Settings**
4. Erstelle einen API Key
5. Kopiere den Key

**Empfohlene Modelle:**
- `sonar` -- Standard-Modell mit Internet-Zugang

**Besonderheit:** Perplexity hat Zugang zum Internet und kann aktuelle Informationen einbeziehen.

### DeepSeek

1. Gehe zu [platform.deepseek.com](https://platform.deepseek.com)
2. Erstelle einen Account
3. Navigiere zu **API Keys**
4. Erstelle einen neuen Key
5. Kopiere den Key

**Empfohlene Modelle:**
- `deepseek-chat` -- Allgemeine Analyse
- `deepseek-coder` -- Code-fokussiert

**Besonderheit:** Extrem guenstig bei guter Qualitaet.

---

## 3. Konfiguration im Bot

### Schritt 1: Settings oeffnen

Im Dashboard navigiere zu **Settings** (Zahnrad-Icon).

### Schritt 2: Tab "LLM Keys" waehlen

Klicke auf den Tab **"LLM Keys"**.

### Schritt 3: API Key eintragen

1. Waehle den gewuenschten Provider aus der Liste
2. Trage deinen API Key in das Eingabefeld ein
3. Klicke auf **"Speichern"**
4. Der Key wird verschluesselt gespeichert

### Schritt 4: Key testen

Nach dem Speichern zeigt die Seite, ob die Verbindung erfolgreich ist. Du siehst:
- **Verbindungsstatus** (verbunden / nicht verbunden)
- **Verfuegbare Modelle** als Chips

### Schritt 5: Im Bot Builder verwenden

Beim Erstellen eines Bots mit der Strategie **LLM Signal** oder **Degen**:

1. Waehle den LLM Provider aus dem Dropdown
2. Waehle das gewuenschte Modell
3. Optional: Passe die Temperatur an (0.0 = deterministisch, 1.0 = kreativ)

---

## 4. Model-Auswahl und Empfehlungen

### Fuer verschiedene Use Cases

| Use Case | Empfohlener Provider | Modell | Warum |
|----------|---------------------|--------|-------|
| **Schnelles Trading (1h)** | Groq | Llama 4 Maverick | Schnellste Antworten |
| **Beste Analyse-Qualitaet** | OpenAI | GPT-4.1 | Praeziseste Vorhersagen |
| **Budget-freundlich** | DeepSeek | DeepSeek V3 Chat | Bestes Preis-Leistungs-Verhaeltnis |
| **Europaeischer Anbieter** | Mistral | Mistral Small 3.2 | EU-Daten-Hosting |
| **Mit Internet-Zugang** | Perplexity | Sonar | Kann aktuelle Daten abfragen |

### Temperatur-Empfehlungen

| Temperatur | Verhalten | Empfohlen fuer |
|-----------|-----------|----------------|
| 0.1 - 0.3 | Sehr konservativ, vorhersagbar | Degen (fester Prompt) |
| 0.3 - 0.5 | Ausgewogen | LLM Signal (Standard) |
| 0.5 - 0.7 | Kreativer, mehr Variation | Experimentelles Trading |
| 0.7 - 1.0 | Sehr kreativ | Nicht empfohlen fuer Trading |

---

## 5. Troubleshooting

### Problem: "API Key invalid"

- Pruefe ob der Key korrekt kopiert wurde (keine Leerzeichen am Anfang/Ende)
- Manche Provider deaktivieren Keys nach laengerer Inaktivitaet
- Erstelle ggf. einen neuen Key

### Problem: "Rate limit exceeded"

- Zu viele Anfragen in kurzer Zeit
- Loesung: Timeframe auf 4h oder Market Sessions aendern
- Manche Provider haben Free-Tier-Limits

### Problem: "Model not found"

- Pruefe ob das Modell noch verfuegbar ist (Provider aendern manchmal Modell-Namen)
- Waehle ein anderes Modell aus der Liste

### Problem: Hohe API-Kosten

- Verwende guenstigere Modelle (GPT-4.1 Mini statt GPT-4.1)
- Wechsle zu Groq oder DeepSeek
- Reduziere die Anzahl der Bots mit LLM-Strategien
- Verwende laengere Timeframes (4h statt 1h = 4x weniger API-Calls)

---

---

# LLM Provider Configuration (English)

> **Note (2026-03-26):** The LLM integration was completely removed in version 4.6.0.
> This guide is kept as an archive reference only.
> The code is archived under git tag `llm-archive-v4.5`.

~~Guide for setting up and configuring supported LLM providers for AI strategies (LLM Signal and Degen).~~

---

## Overview

The **LLM Signal** and **Degen** strategies use external AI models for signal generation. You need at least one API key from one of the following providers:

| Provider | Speed | Cost | Best For |
|----------|-------|------|----------|
| **OpenAI** | Medium | Medium | Best quality analysis |
| **Anthropic** | Medium | Medium | Strong reasoning |
| **Gemini Flash** | Fast | Affordable | Good value |
| **Gemini Pro** | Medium | Medium | Best Google model |
| **Groq** | Very fast | Affordable | Real-time trading |
| **Mistral** | Fast | Affordable | EU data hosting |
| **xAI** | Medium | Medium | Real-time data |
| **Perplexity** | Fast | Medium | Internet access |
| **DeepSeek** | Fast | Very cheap | Best price-performance |

## Getting API Keys

### OpenAI
1. Go to [platform.openai.com](https://platform.openai.com)
2. Navigate to **API Keys**
3. Click **"Create new secret key"**
4. Copy the key (starts with `sk-`)

### Anthropic
1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Navigate to **API Keys** -> **"Create Key"**
3. Copy the key (starts with `sk-ant-`)

### Gemini (Google)
1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Click **"Get API Key"**
3. Create and copy the key

### Groq
1. Go to [console.groq.com](https://console.groq.com)
2. Navigate to **API Keys** -> **"Create API Key"**
3. Copy the key (starts with `gsk_`)

### Mistral
1. Go to [console.mistral.ai](https://console.mistral.ai)
2. Navigate to **API Keys** -> **"Create new key"**
3. Copy the key

### xAI
1. Go to [console.x.ai](https://console.x.ai)
2. Create an API key
3. Copy the key

### Perplexity
1. Go to [docs.perplexity.ai](https://docs.perplexity.ai)
2. Navigate to **API Settings**
3. Create and copy the key

### DeepSeek
1. Go to [platform.deepseek.com](https://platform.deepseek.com)
2. Navigate to **API Keys**
3. Create and copy the key

## Configuring in the Bot

1. Go to **Settings** > **LLM Keys** tab
2. Select the provider
3. Enter your API key
4. Click **"Save"** (key is encrypted at rest)
5. When creating a bot with LLM Signal or Degen strategy, select the provider and model

## Model Recommendations

| Use Case | Provider | Model |
|----------|----------|-------|
| Fast trading (1h) | Groq | Llama 4 Maverick |
| Best analysis | OpenAI | GPT-4.1 |
| Budget-friendly | DeepSeek | DeepSeek V3 Chat |
| EU data hosting | Mistral | Mistral Small 3.2 |
| With internet access | Perplexity | Sonar |

## Temperature Settings

| Temperature | Behavior | Recommended For |
|-------------|----------|-----------------|
| 0.1 - 0.3 | Conservative, predictable | Degen (fixed prompt) |
| 0.3 - 0.5 | Balanced | LLM Signal (default) |
| 0.5 - 0.7 | Creative, more variation | Experimental |
| 0.7 - 1.0 | Very creative | Not recommended for trading |
