# Langboard

Langboard is an **AI Agent Orchestration Platform** that helps organizations run AI workflows with operational control and human oversight.

Unlike traditional automation tools or fully autonomous agent experiments (e.g., AutoGPT, BabyAGI), Langboard strikes the balance between **AI autonomy** and **human governance**, ensuring safe, scalable, and enterprise-ready AI orchestration.

---

## 🌍 Vision and Purpose

AI systems are powerful, but not infallible. Even state-of-the-art large language models (LLMs) hallucinate, misinterpret context, or act unpredictably. Langboard was created with a simple principle:

> **"AI should act, but humans must approve."**

Langboard's mission is to enable enterprises to harness AI efficiency without sacrificing reliability, compliance, or accountability.

---

## 🚀 Quick Start

- Prerequisite: Install **Docker** and **Docker Compose** first.

- For Windows users
  - You can run one of `quickstart.ps1`, `quickstart-ollama-cpu.ps1`, and `quickstart-ollama-gpu.ps1` in `scripts` directory with powershell
    - If the system opens Notepad when you double-click the files, you should select 'Run with powershell' by right-click menu.
  - You can run powershell scripts below

  ```powershell
  cd .\scripts
  .\quickstart.ps1    REM default
  .\quickstart-ollama-cpu.ps1   REM if you want CPU mode
  .\quickstart-ollama-gpu.ps1   REM if you want GPU mode
  ```

- For other OS users,
  - You can double-click one of `quickstart.sh`, `quickstart-ollama-cpu.sh`, and `quickstart-ollama-gpu.sh` in `scripts` directory
  - You can run bash scripts below

  ```bash
  cd ./scripts
  ./quickstart.sh              # default
  ./quickstart-ollama-cpu.sh   # if you want CPU mode
  ./quickstart-ollama-gpu.sh   # if you want GPU mode
  ```

---

## ✨ Platform Overview

1. **Kanban-native workspace**
   - Manage work through boards, columns, and cards.
   - Built-in checklists, comments, attachments, labels, relationships, and wiki pages.

2. **Real-time collaboration**
   - Socket-based updates across boards, cards, wiki, notifications, and bot events.
   - Live editor session events and streaming responses for AI interactions.

3. **AI-assisted work execution**
   - Project bots and internal bots can run tasks, schedules, and scoped automations.
   - Editor chat/copilot flows are available for card and wiki writing workflows.

---

## 🤖 AI Orchestration with Langflow

- Supported bot platforms: `default`, `Langflow`, `n8n`.
- Langflow running modes: `endpoint` and `flow_json`.
- Flow execution endpoints: `/api/v1/run/{anypath}` and `/api/v1/webhook/{anypath}`.
- Built-in packaged flows include `default`, `ollama`, and `lm_studio`.

---

## 🧩 MCP Integration

- Embedded **FastMCP** server is mounted at `/mcp` (streamable HTTP transport).
- MCP tool groups support admin/global and user-scoped governance.
- Requests must include `X-MCP-Tool-Group-UID` for tool-group validation.
- Middleware enforces authentication, ownership checks, and MCP role permissions.
- Built-in MCP tools cover project, card, bot, activity, and metadata operations.
- Card MCP tools include `get_issue_cards` and `create_issue_card` so external
  delivery systems can treat a project board as the issue/scrum source of truth,
  including UI selector cards from frontend development mode.

---

## 🔐 API Keys and Key Vault

- API key lifecycle operations include create, update, activate/deactivate, expiration, and delete.
- IP whitelist validation and API key usage logging are built in.
- Key material is issued through `KeyVault` providers.
- Supported providers: **OpenBao**, **HashiCorp Vault**, **AWS KMS**, **Azure Key Vault**.

---

## 🛡️ Governance and Access Control

- Role-based controls are applied to settings, API keys, MCP, bots, and user management.
- Route-level authorization is enforced through auth and role filters.
- Central settings APIs cover users, bots/internal bots, webhooks, API keys, MCP tool groups, and global relationships.

---

## 🏗️ Architecture

Langboard combines five operational layers:

- **Workspace layer**: board-centric collaboration and AI-assisted editing UI.
- **Application layer**: API and Socket services for orchestration and real-time events.
- **Flow layer**: Langflow runtime service for flow execution and webhooks.
- **Tool layer**: MCP gateway with role-aware tool access and tool-group boundaries.
- **Data and security layer**: PostgreSQL (+ replica/PgBouncer), Redis, Kafka, and KeyVault providers.

---

## 🚚 Deployment Options

Langboard ships as a containerized stack with core services for `server`, `ui`, `api`, `socket`, `flows`, and `celeryworker`.

- Data and messaging services: PostgreSQL, PgBouncer, Redis, Kafka.
- Optional services: OpenBao (`KEY_PROVIDER_TYPE=openbao-local`) and Ollama CPU/GPU profiles.

---

## 🆚 Differentiation

- **vs raw AI libraries**: Langboard adds a collaborative workspace and governance controls, not just SDK primitives.
- **vs standalone flow builders**: Langboard keeps Langflow compatibility while adding user roles, API key governance, and MCP policy boundaries.
- **vs generic automation tools**: Langboard is built around board collaboration plus AI execution, not only background jobs.

---

## 📜 License

Langboard is distributed under a **source-available license inspired by Elastic License v2**.

- ✅ Internal use: free and unlimited.
- ❌ No SaaS resale: cannot be offered as a hosted service without a commercial license.
- ⚖️ Commercial license required: for SaaS, resale, or bundled enterprise offerings.
- 🌐 GitHub Sponsors support is voluntary and does not replace a commercial license.

See [LICENSE](./LICENSE) for full details.

---

## 🤝 Contributing

Contributions are welcome!

- Fork the repository and submit pull requests.
- Report issues and request features.
- Participate in discussions and share workflow templates.

Please follow our [contribution guidelines](./CONTRIBUTING.md).

---

## ❤️ Sponsorship

Langboard development is sustained through **GitHub Sponsors**.

👉 [Sponsor Langboard on GitHub](https://github.com/sponsors/yamonco)

---

## 📧 Contact

For **commercial license inquiries**, **enterprise deployment**, or **partnerships**, please reach out to:

📩 [yamon@yamon.io](mailto:yamon@yamon.io)
