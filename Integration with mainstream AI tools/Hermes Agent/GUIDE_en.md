# Using Huawei Cloud MaaS Models in Hermes Agent

This guide explains how to configure Hermes Agent to use Huawei Cloud International MaaS models (GLM 5.1, DeepSeek, Qwen, etc.) as the inference provider.

> Security note: never paste a real API key into documentation, screenshots, Git commits, or shared chat logs. Use environment variables.

---

## 1. Architecture

Hermes Agent natively supports the `zai` (z.ai / ZhipuAI GLM) provider, which uses the OpenAI-compatible `chat/completions` API format. Huawei Cloud MaaS provides an OpenAI-compatible endpoint at the same path, so no local proxy or protocol adapter is needed — just override the base URL.

```mermaid
flowchart LR
    A[Hermes Agent CLI<br/>hermes] -->|/v1/chat/completions| B[Huawei Cloud International MaaS<br/>api-ap-southeast-1.modelarts-maas.com]
    B --> A
```

No intermediate proxy required. Hermes talks directly to MaaS.

---

## 2. Prerequisites

You need:

- A Huawei Cloud International MaaS API key.
- The MaaS model `glm-5.1` (or other models) enabled for your account.
- Hermes Agent installed (see Section 3).

---

## 3. Install Hermes Agent

### macOS / Linux

Run the official installer:

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

After installation, reload your shell:

```bash
source ~/.zshrc    # macOS
source ~/.bashrc   # Linux
```

### Windows (WSL2)

Hermes Agent does not support native Windows. You must use **WSL2** (Windows Subsystem for Linux).

1. Install WSL2 if you haven't already:

```powershell
# Run in PowerShell as Administrator
wsl --install
```

2. Open a WSL2 terminal (Ubuntu by default), then run the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

3. Reload your shell:

```bash
source ~/.bashrc
```

> **Note:** All Hermes commands run inside WSL2. The config files are located at `/home/<username>/.hermes/` inside the WSL filesystem, not in the Windows `C:\Users\` path.

### Android (Termux)

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

The installer automatically detects Termux and installs a compatible subset of dependencies. See the [Termux guide](https://hermes-agent.nousresearch.com/docs/getting-started/termux) for details.

### Verify Installation

```bash
hermes version
```

Expected output:

```text
Hermes Agent v0.13.0 (2026.5.7)
```

---

## 4. Configuration

Hermes stores configuration in two files:

| File | Purpose |
|---|---|
| `~/.hermes/config.yaml` | Non-secret settings (provider, model, base URL, etc.) |
| `~/.hermes/.env` | API keys and secrets |

### 4.1 Set the API Key

Edit `~/.hermes/.env` and set the GLM provider credentials:

#### macOS / Linux

```bash
nano ~/.hermes/.env
```

Add the following lines:

```bash
GLM_API_KEY=YOUR_HUAWEI_CLOUD_MAAS_API_KEY
GLM_BASE_URL=https://api-ap-southeast-1.modelarts-maas.com/v1
```

#### Windows (WSL2)

Open a WSL2 terminal, then:

```bash
nano ~/.hermes/.env
```

Add the same lines as above. The file is at `/home/<username>/.hermes/.env` inside WSL.

Replace `YOUR_HUAWEI_CLOUD_MAAS_API_KEY` with your actual Huawei Cloud MaaS API token.

> The default `GLM_BASE_URL` is `https://api.z.ai/api/paas/v4` (ZhipuAI's official endpoint). We override it to point to Huawei Cloud MaaS instead.

### 4.2 Set the Model and Provider

Edit `~/.hermes/config.yaml` and update the `model` section:

#### macOS / Linux / WSL2

```bash
nano ~/.hermes/config.yaml
```

Update the `model` section:

```yaml
model:
  default: "glm-5.1"
  provider: "zai"
  base_url: "https://api-ap-southeast-1.modelarts-maas.com/v1"
```

Or use the CLI commands (all platforms):

```bash
hermes config set model.default glm-5.1
hermes config set model.provider zai
hermes config set model.base_url https://api-ap-southeast-1.modelarts-maas.com/v1
```

### 4.3 Verify Configuration

```bash
hermes config
```

Expected output (relevant lines):

```text
◆ Model
  Model:        {'default': 'glm-5.1', 'provider': 'zai', 'base_url': 'https://api-ap-southeast-1.modelarts-maas.com/v1'}
```

```bash
hermes doctor
```

Expected output (relevant lines):

```text
◆ Configuration Files
  ✓ ~/.hermes/.env file exists
  ✓ API key or custom endpoint configured
  ✓ ~/.hermes/config.yaml exists
```

---

## 5. Available Models

Huawei Cloud MaaS (Hong Kong Region) provides the following models:

| Model ID | Provider | Description |
|----------|----------|-------------|
| `glm-5.1` | Zhipu AI | GLM 5.1 — flagship model, comparable to Claude Opus 4.6 |
| `glm-5` | Zhipu AI | GLM 5 |
| `deepseek-v4-flash` | DeepSeek | V4 Flash |
| `DeepSeek-V3` | DeepSeek | V3 |
| `deepseek-v3.2` | DeepSeek | V3.2 |
| `deepseek-v3.1-terminus` | DeepSeek | V3.1 Terminus |
| `qwen3-32b` | Alibaba | Qwen3 32B |

---

## 6. Usage

### Start Chatting

```bash
hermes
```

This starts an interactive TUI session using GLM 5.1 via Huawei Cloud MaaS.

### Switch Models at Runtime

Inside a Hermes chat session:

```bash
/model glm-5
```

Or from the command line:

```bash
hermes model
```

This opens an interactive provider + model picker.

### One-Shot Query

```bash
hermes -z "Explain quantum computing in one paragraph"
```

### Specify Model per Session

```bash
hermes --model deepseek-v4-flash --provider zai
```

---

## 7. Model Aliases (Optional)

Define short aliases for frequently used models in `~/.hermes/config.yaml`:

```yaml
model_aliases:
  glm:
    model: glm-5.1
    provider: zai
    base_url: "https://api-ap-southeast-1.modelarts-maas.com/v1"
  ds:
    model: deepseek-v4-flash
    provider: zai
    base_url: "https://api-ap-southeast-1.modelarts-maas.com/v1"
  qwen:
    model: qwen3-32b
    provider: zai
    base_url: "https://api-ap-southeast-1.modelarts-maas.com/v1"
```

Then inside a chat session:

```bash
/model glm      # switches to glm-5.1
/model ds       # switches to deepseek-v4-flash
/model qwen     # switches to qwen3-32b
```

---

## 8. Switching Between Providers

If you also use other providers (OpenRouter, Anthropic, etc.), you can switch without editing config files:

### CLI flag (per session)

```bash
hermes --provider openrouter --model anthropic/claude-sonnet-4.6
hermes --provider zai --model glm-5.1
```

### Slash command (inside chat)

```bash
/model anthropic/claude-sonnet-4.6 --provider openrouter    # session-only
/model glm-5.1 --provider zai --global                      # also persists to config.yaml
```

---

## 9. Troubleshooting

### `No authenticated providers` in the model picker

Hermes lists a provider only if it has a working credential. Check that `GLM_API_KEY` is set in `~/.hermes/.env`:

```bash
grep GLM_API_KEY ~/.hermes/.env
```

### API connection errors

Verify the endpoint is reachable:

```bash
curl -s -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer YOUR_HUAWEI_CLOUD_MAAS_API_KEY" \
  "https://api-ap-southeast-1.modelarts-maas.com/v1/models"
```

Expected: `200`

### Wrong base URL

Ensure `GLM_BASE_URL` in `~/.hermes/.env` and `model.base_url` in `~/.hermes/config.yaml` both point to:

```text
https://api-ap-southeast-1.modelarts-maas.com/v1
```

Not the Anthropic-compatible path (`/anthropic`) — the `zai` provider uses the OpenAI-compatible format.

### Run diagnostics

```bash
hermes doctor
```

---

## 10. Comparison with Other Tools

| Feature | Hermes Agent + MaaS | Claude Code + MaaS | Codex + MaaS |
|---------|--------------------|--------------------|--------------|
| Local proxy required | No | No | Yes (LiteLLM + Responses adapter) |
| Native GLM provider | Yes (`zai`) | No (uses Anthropic wire) | No |
| Interactive model picker | Yes (`hermes model`) | No | No |
| Model switching at runtime | Yes (`/model`) | No (restart needed) | No |
| Multi-platform gateway | Yes (Telegram, Discord, etc.) | No | No |

---

## 11. Current Verified Result

The current setup has been verified with:

```text
hermes version: ok (v0.13.0)
hermes config: ok (provider: zai, model: glm-5.1)
hermes doctor: ok (API key configured)
```

Daily use command:

```bash
hermes
```
