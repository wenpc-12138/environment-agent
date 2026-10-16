# 生态Agent（Environment Agent）

> 面向生态环境行业的**桌面级行业智能体工作台** —— 不只是问答机器人，而是把「查标准 → 算数据 → 写报告 → 审报告 → 沉淀知识 → 定时任务」整条业务链路口径化、可追溯地跑完的私有化 Agent。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey.svg)

[English](README.md) | **简体中文**

---

## 目录

- [为什么需要它](#为什么需要它)
- [核心能力](#核心能力)
- [自我进化：对标 Hermes 类自治 Agent](#自我进化对标-hermes-类自治-agent)
- [架构总览](#架构总览)
- [快速开始](#快速开始)
- [接入大模型（密钥不写进代码）](#接入大模型密钥不写进代码)
- [联网搜索（可选）](#联网搜索可选)
- [目录结构](#目录结构)
- [测试](#测试)
- [数据与隐私](#数据与隐私)
- [常见问题](#常见问题)
- [License](#license)

---

## 为什么需要它

通用大模型能写代码、能聊天，但让它回答「氨氮排放限值是多少」「出一份验收监测报告」，它往往需要现场查、且对环保法规没有把握。

生态Agent 把这些能力**预置进产品**：内置标准库检索、法规库、行业公式、报告模板、CMA 合规规则与审核角色。所有专业结论都要求**带标准号与出处**，不确定就标注「待核实」，而不是编造。

一句话对比：

| | 通用 Agent（如 Claude Code / Cursor） | 生态Agent |
|---|---|---|
| 定位 | 编程/通用任务的「全能选手」 | 环保业务上「能独立顶岗的专业选手」 |
| 领域知识 | 需现场检索，法规把握弱 | 标准库/法规库/公式/模板开箱即用 |
| 结论口径 | 通用 | 标准引用不编造、报告要过审、知识要沉淀 |
| 部署 | 云端为主 | 桌面私有化，数据不出本机 |
| 协作 | —— | 提供标准接口，可与通用 Agent 配合 |

---

## 核心能力

- **任务/会话体系**：多任务并行，SQLite 持久化，任务间上下文互不污染
- **三种模式**：`craft`（执行）/ `ask`（问答）/ `plan`（规划）
- **多 Provider**：任意 OpenAI 兼容端点（DeepSeek / OpenAI / 智谱 GLM / 通义 Qwen / 本地 Ollama），**内置免密钥演示模式**
- **KB 优先查库**：FTS5 全文 + 向量 + 关系多路召回（RRF 融合），联网搜索补充，五分类落库（网络资料/政府发布/标准规范/政策法规/其他）
- **Skill 技能系统**：`data/agents/skills/*/SKILL.md` 自动扫描加载，可开关；随包附带 22 个行业技能（验收报告、环评、碳排放、CMA 合规、各类监测…）
- **多专家角色协作**：报告编排、专家评审、角色分工与团队注册表
- **报告中心**：报告模板学习、按类型生成、公式计算、Word/PDF 导出、三级审核
- **任务记忆**：项目事实持久化，跨会话注入（含画像/事实/关系/ episode 向量）
- **上下文压缩**：超软预算自动把旧轮次摘要化，保留最近轮次原文；硬预算告警
- **缓存命中记账**：解析 DeepSeek 硬盘缓存 / OpenAI `cached_tokens`，展示命中率与节省量
- **流式输出**：SSE 实时渲染，工具调用以卡片展示
- **定时任务（Cron）**：应用内调度器，支持任务 notepad / 连续上下文 / 上次摘要
- **审计与安全**：审计日志、R8 自学习产物审核闸门、网关层统一入口
- **双入口前端**：v1.2 模板界面（`/legacy`）+ Vue3 + Vite 界面（聊天/知识库/报告/计划）

---

## 自我进化：对标 Hermes 类自治 Agent

生态Agent 具备一条完整的**自进化闭环（OERCR）**，与当前前沿自治 Agent 的设计路线一致：

```
Observe 观察  →  Reflect 反思  →  Crystallize 沉淀  →  Reuse 复用
   (任务执行)      (复盘归纳)        (固化为技能/模板)     (下次自动命中)
```

- **经验自动结晶**：一次成功的任务流程会被抽象为可复用技能（`SKILL.md` 与模板文件）
- **R8 审核闸门**：任何自学产物必须通过审核才能进入生效状态，避免「学错」
- **技能迭代与升级提案**：技能带版本，运行中产生 `skill_update_proposals`，人工确认后升级
- **记忆闭环**：事实 / 画像 / 关系 / 情节向量多路召回，越用越懂你的业务口径
- **模板学习**：投喂一批报告即可自动识别类型、聚类、注册新报告类型并生成模板骨架

> 说明：能力边界以代码实现为准，本仓库不含任何模拟/伪造的「自我进化」演示数据。

---

## 架构总览

项目已从 v1.2 单体 + v2.0 分层的**双轨**状态，收敛为**以 `src/` 为唯一实现的单轨**结构；根目录同名文件均为**薄兼容壳**（`from src.* import ...`），老代码 `import app` / `import db` 的用法保持不变。

```
L1 网关      src/gateway/         Flask Web API(SSE) · 222 条路由 · MCP server · CLI
L2 推理      src/agent/ · src/llm/ ReAct 主循环(≤8 轮) · Provider 池 · 路由与意图
L3 工具      src/tools/ · src/skills/  kb/web/计算/文档 · SKILL.md 执行链
L4 记忆知识  src/memory/ · src/kb/     FTS5 + 向量 + 关系 · 事实/画像/情节
L5 领域      src/report/ · src/compliance/ · src/compute/  报告/合规/公式
L6 协作      src/agents/ · src/roles/ · src/teams/ · src/workflow/  子代理/角色/团队/工作流
L7 学习      src/learn/ · src/obs/     OERCR 结晶 · R8 审核 · 审计与可观测
```

- **契约优先**：`src/models/core.py` 以 Pydantic v2 定义核心模型，接口变更需过契约测试
- **数据层**：SQLite + WAL，17 个幂等迁移脚本（`db/migrations/`），老库平滑演进不丢数据
- **事件协议**：SSE 事件（budget/usage/reasoning/delta/tool_start/tool_end/assistant_done/done…）保持稳定

---

## 快速开始

### 环境要求

- Python **3.10+**（开发环境使用 3.14）
- 桌面窗口模式需 `pywebview`（已在依赖内）；无图形环境请用 `--browser` 模式
- 联网搜索为**可选**能力（依赖 SearXNG），未配置时自动降级，不影响本地知识库问答

### 安装与启动

```bash
git clone <your-repo-url>
cd environment-agent

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 桌面窗口（默认，优先 pywebview）
python run.py

# 浏览器模式 / 指定端口
python run.py --browser
python run.py --port 5837
```

首次启动会自动初始化数据库、执行 17 个迁移并注入**演示知识库种子**，稍等片刻即可使用。

> 注意：请用 `run.py` 启动。直接 `python app.py` 只跑 Flask（默认端口 5837），不含桌面壳与 SearXNG 守护。

### 演示模式（零密钥体验）

首次启动默认激活「**演示模式**」Provider（`kind=mock`）：无需任何 API Key，即可体验完整闭环 —— 提问 → `kb_lookup` 检索本地知识库 → 工具卡片 → 流式回答。

---

## 接入大模型（密钥不写进代码）

**本仓库不包含任何 API Key**：Provider 表中预置的 6 个 Provider 密钥一律为空，演示模式默认激活。密钥只有两种注入方式，且都不会进入版本库。

### 方式一：界面配置（推荐给桌面用户）

左侧「设置」→ Provider 列表 → 选择预设（DeepSeek / OpenAI / GLM / Qwen / Ollama）或自定义 → 填入 **API Key** → 「测试连接」→ 激活。

密钥保存于本机 SQLite（`data/ecoagent.db`），该文件已被 `.gitignore` 排除。

### 方式二：环境变量（推荐给容器 / CI / 无界面）

```bash
cp .env.example .env      # .env 已在 .gitignore 中
# 编辑 .env：
# EA_LLM_API_KEY=sk-xxxxxxxx
# EA_LLM_BASE_URL=https://api.deepseek.com
# EA_LLM_MODEL=deepseek-chat
# EA_LLM_PROVIDER=DeepSeek        # 可选：指定目标 Provider

python run.py
```

启动时 `apply_env_override()` 会把变量写入目标 Provider 并自动激活；**未设置任何 `EA_LLM_*` 变量时不做任何改动**。

| 变量 | 说明 |
|---|---|
| `EA_LLM_API_KEY` | API 密钥 |
| `EA_LLM_BASE_URL` | OpenAI 兼容端点 |
| `EA_LLM_MODEL` | 模型名 |
| `EA_LLM_PROVIDER` | 目标 Provider 名称（可选） |
| `PORT` | 服务端口，`0` = 自动挑空闲端口 |
| `ECOAGENT_DB` | 覆盖数据库文件路径 |

> 🔐 **安全提示**：不要把 `.env`、`data/ecoagent.db` 或任何含密钥的文件提交到仓库。若曾误提交，请立即到服务商后台**吊销并轮换密钥**（历史提交中的密钥无法靠删除文件消除）。

---

## 联网搜索（可选）

联网搜索走自建 [SearXNG](https://github.com/searxng/searxng)（免 API Key 的元搜索）：

```bash
python install_searxng.py        # 安装到 runtime/searxng
python run.py                    # 启动时自动守护拉起 SearXNG（幂等 + 30s 自愈）
```

配置见 `data/searxng.json`，或使用环境变量 `SEARXNG_URL` / `SEARXNG_ENABLED` / `SEARXNG_MAX_RESULTS` 等覆盖。
未部署 SearXNG 时，`web_search` 工具会返回失败信息，**不影响主流程**。

---

## 目录结构

```
environment-agent/
├── run.py                    # 启动入口（桌面窗口/浏览器，含 SearXNG 守护）
├── app.py                    # Flask 入口（薄壳，create_app 在 src/gateway）
├── db.py / tools.py / ...    # v1.2 兼容薄壳，实际实现均在 src/
├── seed.py                   # 演示知识库种子
├── kb_pipeline.py            # 知识库解析/分块/嵌入管线（PDF/Word/Excel/OCR）
├── ocr_*.py / vlm_convert.py  # OCR 与图像转换（RapidOCR 等）
├── report_*.py               # 报告计算/学习/编排/重写
├── searxng_*.py              # SearXNG 启动器与 MCP 适配
├── src/                      # v2.0 分层实现（唯一实现来源，22 个包）
│   ├── gateway/  agent/  llm/  tools/  skills/
│   ├── memory/   kb/     report/  compliance/  compute/
│   ├── agents/   roles/  teams/   workflow/   scheduler.py
│   ├── learn/    obs/    security/  public_api/  vision/
│   └── models/   core/           # 契约模型与配置
├── db/migrations/            # 17 个幂等迁移脚本
├── templates/  static/       # v1.2 前端（static/vditor 为编辑器依赖）
├── web/                      # Vue3 + Vite 前端源码（构建产物在 static/vue）
├── tests/                    # 86 个测试文件（契约/单元/E2E）
├── assets/                   # 图标
├── extras/searxng/           # SearXNG 部署示例（docker-compose / settings 样例）
└── data/                     # 默认配置与演示技能（运行时会生成 DB/上传/日志，已忽略）
```

> 本仓库只分发**代码**：架构说明、契约与设计文档不随代码分发。

---

## 测试

```bash
python -m pytest -q                 # 全量
python -m pytest tests/core -q      # 配置与数据层
python -m pytest -m contract        # 契约签名测试
```

当前基线：**810 passed / 0 failed / 1 skipped**（86 个测试文件，含契约、单元与端到端）。

> 跳过项是「与遗留 `db.py` 备份做公共名比对」的兼容性用例：该备份文件不随仓库分发。

> 提示：`pytest.ini` 默认带 `-q`，如需查看通过数量汇总，可加 `-o addopts=""`，例如
> `python -m pytest -o addopts="" --tb=line`。

测试全部使用临时库隔离，不会读写你的 `data/ecoagent.db`。

---

## 数据与隐私

- **本地优先**：数据库为本地 SQLite（`data/ecoagent.db`），会话、知识库、记忆、审计日志均不出本机
- **可完全离线**：演示模式 + 本地知识库即可闭环；接入本地 Ollama 时数据不出网
- **仓库不含用户数据**：`data/` 下的数据库、备份、上传、任务产物、学习记录均已通过 `.gitignore` 排除，仅保留默认配置（`searxng.json`、`report_types.json`）与演示技能
- **审计与闸门**：审计日志记录关键操作；自学习产物需过 R8 审核才生效

---

## 常见问题

**Q：启动后左侧没有可用的模型？**
默认激活的是「演示模式」。要接真实模型，按[接入大模型](#接入大模型密钥不写进代码)配置；注意 Provider 需要 `base_url` + `model` + `api_key` 三者齐备。

**Q：联网搜索失败？**
属预期降级。部署 SearXNG（`python install_searxng.py`）后重启即可。

**Q：想换数据库位置？**
设置环境变量 `ECOAGENT_DB=/path/to/ecoagent.db`。

**Q：端口被占用？**
`python run.py --port 6000`，或 `python run.py`（自动挑空闲端口）。

**Q：公司/VPN 代理环境下，本机功能（搜索/OCR）超时？**
本机流量已自动排除代理：`ensure_local_no_proxy()` 会把 `127.0.0.1 / localhost / ::1` 写入 `no_proxy`，本机 webhook 推送使用直连 opener（`src/core/net.py`）。外部接口仍遵循你的代理设置。

**Q：知识库/报告内容涉及版权？**
知识库内容由使用者自行入库，仓库不分发任何第三方标准全文；请遵守标准出版方的授权要求。

---

## License

本项目基于 **MIT License** 开源，版权人 **qiumaimai**，详见 [LICENSE](LICENSE)。

第三方依赖（Flask、Pydantic、Vite、Vditor、SearXNG 等）遵循各自许可证。
