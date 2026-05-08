# 在 Hermes Agent 中使用华为云 MaaS 模型

本指南说明如何将 Hermes Agent 配置为使用华为云国际站 MaaS 模型（GLM 5.1、DeepSeek、Qwen 等）作为推理供应商。

> 安全提醒：不要把真实 API Key 写进文档、截图、Git 提交或共享聊天记录。请使用环境变量。

---

## 1. 架构

Hermes Agent 原生支持 `zai`（z.ai / 智谱 GLM）供应商，使用 OpenAI 兼容的 `chat/completions` API 格式。华为云 MaaS 在相同路径下提供 OpenAI 兼容端点，因此无需本地代理或协议适配层——只需覆盖 base URL 即可。

```mermaid
flowchart LR
    A[Hermes Agent CLI<br/>hermes] -->|/v1/chat/completions| B[华为云国际站 MaaS<br/>api-ap-southeast-1.modelarts-maas.com]
    B --> A
```

无需中间代理。Hermes 直接与 MaaS 通信。

---

## 2. 前置条件

你需要：

- 华为云国际站 MaaS API Key。
- 账号已开通 MaaS 模型 `glm-5.1`（或其他模型）。
- 已安装 Hermes Agent（见第 3 节）。

---

## 3. 安装 Hermes Agent

### macOS / Linux

运行官方安装脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

安装完成后，重新加载 Shell：

```bash
source ~/.zshrc    # macOS
source ~/.bashrc   # Linux
```

### Windows（WSL2）

Hermes Agent 不支持原生 Windows，必须使用 **WSL2**（Windows Subsystem for Linux）。

1. 如果尚未安装 WSL2，先安装：

```powershell
# 在 PowerShell（管理员）中运行
wsl --install
```

2. 打开 WSL2 终端（默认为 Ubuntu），然后运行安装脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

3. 重新加载 Shell：

```bash
source ~/.bashrc
```

> **注意：** 所有 Hermes 命令都在 WSL2 内运行。配置文件位于 WSL 文件系统内的 `/home/<username>/.hermes/`，而非 Windows 的 `C:\Users\` 路径。

### Android（Termux）

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

安装脚本会自动检测 Termux 环境并安装兼容的依赖子集。详见 [Termux 指南](https://hermes-agent.nousresearch.com/docs/getting-started/termux)。

### 验证安装

```bash
hermes version
```

预期输出：

```text
Hermes Agent v0.13.0 (2026.5.7)
```

---

## 4. 配置

Hermes 的配置存储在两个文件中：

| 文件 | 用途 |
|---|---|
| `~/.hermes/config.yaml` | 非密钥设置（供应商、模型、base URL 等） |
| `~/.hermes/.env` | API 密钥和敏感信息 |

### 4.1 设置 API Key

编辑 `~/.hermes/.env`，设置 GLM 供应商凭据：

#### macOS / Linux

```bash
nano ~/.hermes/.env
```

添加以下内容：

```bash
GLM_API_KEY=YOUR_HUAWEI_CLOUD_MAAS_API_KEY
GLM_BASE_URL=https://api-ap-southeast-1.modelarts-maas.com/v1
```

#### Windows（WSL2）

打开 WSL2 终端，然后：

```bash
nano ~/.hermes/.env
```

添加与上方相同的内容。文件位于 WSL 内的 `/home/<username>/.hermes/.env`。

将 `YOUR_HUAWEI_CLOUD_MAAS_API_KEY` 替换为你的华为云 MaaS API Token。

> 默认 `GLM_BASE_URL` 为 `https://api.z.ai/api/paas/v4`（智谱 AI 官方端点）。我们将其覆盖为华为云 MaaS 端点。

### 4.2 设置模型和供应商

编辑 `~/.hermes/config.yaml`，更新 `model` 部分：

#### macOS / Linux / WSL2

```bash
nano ~/.hermes/config.yaml
```

更新 `model` 部分：

```yaml
model:
  default: "glm-5.1"
  provider: "zai"
  base_url: "https://api-ap-southeast-1.modelarts-maas.com/v1"
```

或使用 CLI 命令（所有平台通用）：

```bash
hermes config set model.default glm-5.1
hermes config set model.provider zai
hermes config set model.base_url https://api-ap-southeast-1.modelarts-maas.com/v1
```

### 4.3 验证配置

```bash
hermes config
```

预期输出（相关行）：

```text
◆ Model
  Model:        {'default': 'glm-5.1', 'provider': 'zai', 'base_url': 'https://api-ap-southeast-1.modelarts-maas.com/v1'}
```

```bash
hermes doctor
```

预期输出（相关行）：

```text
◆ Configuration Files
  ✓ ~/.hermes/.env file exists
  ✓ API key or custom endpoint configured
  ✓ ~/.hermes/config.yaml exists
```

---

## 5. 可用模型

华为云 MaaS（香港区域）提供以下模型：

| 模型 ID | 厂商 | 说明 |
|---------|------|------|
| `glm-5.1` | 智谱 AI | GLM 5.1 — 旗舰模型，能力对标 Claude Opus 4.6 |
| `glm-5` | 智谱 AI | GLM 5 |
| `deepseek-v4-flash` | DeepSeek | V4 Flash |
| `DeepSeek-V3` | DeepSeek | V3 |
| `deepseek-v3.2` | DeepSeek | V3.2 |
| `deepseek-v3.1-terminus` | DeepSeek | V3.1 Terminus |
| `qwen3-32b` | 阿里 | Qwen3 32B |

---

## 6. 使用方式

### 开始对话

```bash
hermes
```

启动交互式 TUI 会话，使用 GLM 5.1（通过华为云 MaaS）。

### 运行时切换模型

在 Hermes 对话会话内：

```bash
/model glm-5
```

或从命令行：

```bash
hermes model
```

打开交互式供应商 + 模型选择器。

### 单次查询

```bash
hermes -z "用一段话解释量子计算"
```

### 按会话指定模型

```bash
hermes --model deepseek-v4-flash --provider zai
```

---

## 7. 模型别名（可选）

在 `~/.hermes/config.yaml` 中为常用模型定义短别名：

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

然后在对话会话内：

```bash
/model glm      # 切换到 glm-5.1
/model ds       # 切换到 deepseek-v4-flash
/model qwen     # 切换到 qwen3-32b
```

---

## 8. 在不同供应商之间切换

如果你同时使用其他供应商（OpenRouter、Anthropic 等），无需编辑配置文件即可切换：

### CLI 参数（仅当前会话）

```bash
hermes --provider openrouter --model anthropic/claude-sonnet-4.6
hermes --provider zai --model glm-5.1
```

### 斜杠命令（对话内）

```bash
/model anthropic/claude-sonnet-4.6 --provider openrouter    # 仅当前会话
/model glm-5.1 --provider zai --global                      # 同时持久化到 config.yaml
```

---

## 9. 故障排查

### 模型选择器显示"无已认证供应商"

Hermes 仅在检测到有效凭据时才列出供应商。检查 `~/.hermes/.env` 中是否设置了 `GLM_API_KEY`：

```bash
grep GLM_API_KEY ~/.hermes/.env
```

### API 连接错误

验证端点是否可达：

```bash
curl -s -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer YOUR_HUAWEI_CLOUD_MAAS_API_KEY" \
  "https://api-ap-southeast-1.modelarts-maas.com/v1/models"
```

预期：`200`

### base URL 错误

确保 `~/.hermes/.env` 中的 `GLM_BASE_URL` 和 `~/.hermes/config.yaml` 中的 `model.base_url` 都指向：

```text
https://api-ap-southeast-1.modelarts-maas.com/v1
```

而非 Anthropic 兼容路径（`/anthropic`）——`zai` 供应商使用 OpenAI 兼容格式。

### 运行诊断

```bash
hermes doctor
```

---

## 10. 与其他工具的对比

| 特性 | Hermes Agent + MaaS | Claude Code + MaaS | Codex + MaaS |
|------|--------------------|--------------------|--------------|
| 需要本地代理 | 否 | 否 | 是（LiteLLM + Responses 适配层） |
| 原生 GLM 供应商支持 | 是（`zai`） | 否（使用 Anthropic 协议） | 否 |
| 交互式模型选择器 | 是（`hermes model`） | 否 | 否 |
| 运行时切换模型 | 是（`/model`） | 否（需重启） | 否 |
| 多平台消息网关 | 是（Telegram、Discord 等） | 否 | 否 |

---

## 11. 当前已验证结果

当前配置已验证：

```text
hermes version: ok (v0.13.0)
hermes config: ok (provider: zai, model: glm-5.1)
hermes doctor: ok (API key configured)
```

日常使用命令：

```bash
hermes
```
