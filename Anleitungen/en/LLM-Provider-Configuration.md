# LLM Provider Configuration

Guide for setting up and configuring supported LLM providers for AI strategies (LLM Signal and Degen).

---

## Table of Contents

1. [Overview](#1-overview)
2. [Provider Details](#2-provider-details)
3. [Configuring in the Bot](#3-configuring-in-the-bot)
4. [Model Selection and Recommendations](#4-model-selection-and-recommendations)
5. [Troubleshooting](#5-troubleshooting)

---

## 1. Overview

The **LLM Signal** and **Degen** strategies use external AI models for signal generation. You need at least one API key from one of the following providers:

| Provider | Models | Speed | Cost | Recommendation |
|----------|--------|-------|------|----------------|
| **OpenAI** | GPT-4.1, GPT-4.1 Mini | Medium | Medium | Best quality |
| **Anthropic** | Claude Haiku 4.5 | Medium | Medium | Excellent for analysis |
| **Gemini Flash** | Gemini 2.5 Flash | Fast | Affordable | Good value for money |
| **Gemini Pro** | Gemini 3 Pro (Preview) | Medium | Medium | Best Google model |
| **Groq** | Llama 4 Maverick | Very fast | Affordable | Fastest responses |
| **Mistral** | Mistral Small 3.2 | Fast | Affordable | European provider |
| **xAI** | Grok 3 Mini | Medium | Medium | Real-time data |
| **Perplexity** | Sonar | Fast | Medium | Internet access |
| **DeepSeek** | DeepSeek V3 Chat, DeepSeek Reasoner | Fast | Very cheap | Best price-performance ratio |

---

## 2. Provider Details

### OpenAI

1. Go to [platform.openai.com](https://platform.openai.com)
2. Create an account or log in
3. Navigate to **API Keys** (left side)
4. Click on **"Create new secret key"**
5. Give the key a name (e.g., "Trading Bot")
6. Copy the key (starts with `sk-`)

**Important:** The key is only shown once! Save it securely.

**Recommended models:**
- `gpt-4.1` -- Best quality, higher price
- `gpt-4.1-mini` -- More affordable, sufficient for most use cases (default)

### Anthropic

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an account
3. Navigate to **API Keys**
4. Click on **"Create Key"**
5. Copy the key (starts with `sk-ant-`)

**Recommended models:**
- `claude-haiku-4-5-20251001` -- Fast and affordable (default)

### Gemini (Google)

1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Log in with your Google account
3. Click on **"Get API Key"**
4. Create a key in a new or existing project
5. Copy the key

**Recommended models:**
- `gemini-3-pro-preview` -- Best Google model (as `gemini_pro` provider)
- `gemini-2.5-flash` -- Faster, more affordable (default for `gemini` provider)

### Groq

1. Go to [console.groq.com](https://console.groq.com)
2. Create an account
3. Navigate to **API Keys**
4. Click on **"Create API Key"**
5. Copy the key (starts with `gsk_`)

**Recommended models:**
- `meta-llama/llama-4-maverick-17b-128e-instruct` -- Llama 4 Maverick (default)

**Special feature:** Groq offers **extremely fast inference** (often < 1 second). Ideal for real-time trading.

### Mistral

1. Go to [console.mistral.ai](https://console.mistral.ai)
2. Create an account
3. Navigate to **API Keys**
4. Click on **"Create new key"**
5. Copy the key

**Recommended models:**
- `mistral-small-2506` -- Mistral Small 3.2 (default)

### xAI (Grok)

1. Go to [console.x.ai](https://console.x.ai)
2. Log in (X/Twitter account required)
3. Navigate to **API Keys**
4. Create a new key
5. Copy the key

**Recommended models:**
- `grok-3-mini` -- Grok 3 Mini (default)

### Perplexity

1. Go to [docs.perplexity.ai](https://docs.perplexity.ai)
2. Create an account
3. Navigate to **API Settings**
4. Create an API key
5. Copy the key

**Recommended models:**
- `sonar` -- Default model with internet access

**Special feature:** Perplexity has access to the internet and can include up-to-date information.

### DeepSeek

1. Go to [platform.deepseek.com](https://platform.deepseek.com)
2. Create an account
3. Navigate to **API Keys**
4. Create a new key
5. Copy the key

**Recommended models:**
- `deepseek-chat` -- General analysis
- `deepseek-coder` -- Code-focused

**Special feature:** Extremely affordable with good quality.

---

## 3. Configuring in the Bot

### Step 1: Open Settings

In the dashboard, navigate to **Settings** (gear icon).

### Step 2: Select the "LLM Keys" Tab

Click on the **"LLM Keys"** tab.

### Step 3: Enter the API Key

1. Select the desired provider from the list
2. Enter your API key in the input field
3. Click on **"Save"**
4. The key is stored encrypted

### Step 4: Test the Key

After saving, the page shows whether the connection is successful. You will see:
- **Connection status** (connected / not connected)
- **Available models** as chips

### Step 5: Use in the Bot Builder

When creating a bot with the **LLM Signal** or **Degen** strategy:

1. Select the LLM provider from the dropdown
2. Select the desired model
3. Optional: Adjust the temperature (0.0 = deterministic, 1.0 = creative)

---

## 4. Model Selection and Recommendations

### For Different Use Cases

| Use Case | Recommended Provider | Model | Why |
|----------|----------------------|-------|-----|
| **Fast trading (1h)** | Groq | Llama 4 Maverick | Fastest responses |
| **Best analysis quality** | OpenAI | GPT-4.1 | Most precise predictions |
| **Budget-friendly** | DeepSeek | DeepSeek V3 Chat | Best price-performance ratio |
| **European provider** | Mistral | Mistral Small 3.2 | EU data hosting |
| **With internet access** | Perplexity | Sonar | Can query current data |

### Temperature Recommendations

| Temperature | Behavior | Recommended For |
|-------------|----------|-----------------|
| 0.1 - 0.3 | Very conservative, predictable | Degen (fixed prompt) |
| 0.3 - 0.5 | Balanced | LLM Signal (default) |
| 0.5 - 0.7 | More creative, more variation | Experimental trading |
| 0.7 - 1.0 | Very creative | Not recommended for trading |

---

## 5. Troubleshooting

### Issue: "API Key invalid"

- Check if the key was copied correctly (no spaces at the beginning/end)
- Some providers deactivate keys after extended inactivity
- Create a new key if necessary

### Issue: "Rate limit exceeded"

- Too many requests in a short time
- Solution: Change the timeframe to 4h or Market Sessions
- Some providers have free-tier limits

### Issue: "Model not found"

- Check if the model is still available (providers sometimes change model names)
- Select a different model from the list

### Issue: High API costs

- Use more affordable models (GPT-4.1 Mini instead of GPT-4.1)
- Switch to Groq or DeepSeek
- Reduce the number of bots with LLM strategies
- Use longer timeframes (4h instead of 1h = 4x fewer API calls)
