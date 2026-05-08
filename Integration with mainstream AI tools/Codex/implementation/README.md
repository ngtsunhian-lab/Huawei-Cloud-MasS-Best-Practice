# Huawei Cloud MaaS for Codex via LiteLLM

Local LiteLLM proxy configuration for using Huawei Cloud MaaS models from Codex.

## What this runs

Codex talks to a local OpenAI-compatible Responses API endpoint:

```text
Codex -> http://127.0.0.1:8787/v1/responses -> local Responses adapter -> LiteLLM -> Huawei Cloud MaaS /openai/v1/chat/completions
```

The default model is `glm-5.1`, matching the existing Codex `maas-glm` profile.

## Environment

Set these before starting the proxy:

```sh
export MAAS_API_KEY="your-huawei-cloud-maas-api-key"
export MAAS_API_BASE="https://api-ap-southeast-1.modelarts-maas.com/openai/v1"
```

The default endpoint is Huawei Cloud International CN-Hong Kong:

```text
https://api-ap-southeast-1.modelarts-maas.com/openai/v1
```

If `MAAS_API_BASE` is not set, `scripts/start.sh` uses that international endpoint.

## Install

```sh
uv tool install 'litellm[proxy]'
```

If `uv` is not available:

```sh
python3 -m pip install 'litellm[proxy]'
```

On this Mac, `pip --user` installs the `litellm` command under
`~/Library/Python/3.9/bin`; `scripts/start.sh` adds that path automatically.

## Start

```sh
./scripts/start.sh
```

The Codex-facing adapter listens on `http://127.0.0.1:8787`.
LiteLLM listens internally on `http://127.0.0.1:8788`.

## Verify

With the proxy running:

```sh
python3 scripts/verify.py
```

The script checks:

- `/v1/chat/completions`
- `/v1/responses`
- streaming `/v1/responses`

## Codex

The existing Codex profile should keep working:

```sh
codex --profile maas-glm
```

The relevant provider should point at:

```toml
[model_providers.huawei-maas-proxy]
base_url = "http://127.0.0.1:8787/v1"
env_key = "MAAS_API_KEY"
```
