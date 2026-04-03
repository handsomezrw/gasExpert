# 阶段 5 实施总结：可观测性 + Docker 容器化

> 对应 PLAN.md 阶段 5（已完成 [x]）

---

## 一、完成的工作

### 1. 可观测性

#### structlog 结构化日志

| 项目 | 内容 |
|------|------|
| 文件 | `backend/app/logging_config.py` |
| 开发模式 | 自动检测终端 TTY → 彩色控制台输出 |
| 生产模式 | Docker 或 `LOG_FORMAT=json` → JSON Lines（一行一对象，可被 ELK/Loki 等直接采集） |
| 日志内容 | ISO 时间戳、日志级别、logger 名称、上下文变量 |
| 降噪 | `httpcore`、`httpx`、`chromadb`、`urllib3` 级别设为 WARNING |

#### HTTP 请求日志中间件

| 项目 | 内容 |
|------|------|
| 位置 | `backend/app/main.py` — FastAPI `@app.middleware("http")` |
| 记录字段 | `method`、`path`、`status`、`elapsed_ms` |
| 排除 | `/api/health`（高频探针不记录） |

示例日志（JSON 模式）：

```json
{"method":"POST","path":"/api/chat/stream","status":200,"elapsed_ms":23451.2,"event":"http_request","level":"info","timestamp":"2026-03-30T01:23:45.678Z"}
```

#### LangSmith 全链路追踪

| 项目 | 内容 |
|------|------|
| 接入方式 | 环境变量驱动 — `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` |
| 无侵入 | LangChain/LangGraph 自动上报，无需改动业务代码 |
| 追踪内容 | Agent 每个节点（Planner/ToolExecutor/RAG/Reflector/Responder）的输入输出、LLM token 用量、工具执行耗时 |
| 配置文件 | `.env` / `.env.example` 中已预留三个变量 |

启用方法：

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_xxxx
LANGCHAIN_PROJECT=gas-copilot
```

在 [smith.langchain.com](https://smith.langchain.com) 中可查看完整的调用链路。

---

### 2. Docker 容器化

#### 后端 Dockerfile (`backend/Dockerfile`)

| 项目 | 内容 |
|------|------|
| 基础镜像 | `python:3.12-slim` |
| 依赖安装 | `requirements-rag.txt`（含全部 RAG 依赖） |
| 运行命令 | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| 日志模式 | `LOG_FORMAT=json` 自动启用 |
| 暴露端口 | 8000（容器内） |

#### 前端 Dockerfile (`frontend/Dockerfile`)

| 项目 | 内容 |
|------|------|
| 构建阶段 | `node:20-alpine` → `npm ci` + `npm run build` |
| 运行阶段 | `nginx:alpine` 托管静态文件 |
| 反向代理 | `nginx.conf` 将 `/api/` 转发到 `backend:8000` |
| SSE 支持 | `proxy_buffering off`，`proxy_read_timeout 300s` |
| 暴露端口 | 80（容器内） |

#### docker-compose.yml

```yaml
services:
  backend:   # 端口映射 8080:8000，健康检查，数据卷持久化
  frontend:  # 端口映射 3000:80，依赖 backend
volumes:
  backend-data:  # 持久化 SQLite + ChromaDB + RAG chunks
```

| 服务 | 宿主机端口 | 说明 |
|------|:----------:|------|
| frontend | 3000 | 浏览器访问入口 |
| backend | 8080 | API 端点（可选直连） |

---

### 3. 项目基础设施

| 文件 | 说明 |
|------|------|
| `README.md` | 项目说明、功能列表、技术栈、快速开始（本地 + Docker）、配置项速查 |
| `.gitignore` | 排除 `.venv`、`node_modules`、`.env`、生成数据（chroma/db/chunks） |
| `.dockerignore`（×3） | 根目录 + backend + frontend，排除开发文件 |
| `.env.example` | 清理了真实密钥，改为占位符，增加注释说明 |

---

## 二、验证方法

### 1. structlog 配置验证

```powershell
cd gas-copilot\backend
.venv\Scripts\python -c "
from app.logging_config import setup_logging
import structlog
setup_logging()
log = structlog.get_logger()
log.info('test_event', key='value', number=42)
print('structlog OK')
"
```

**预期**：终端中看到带颜色的结构化日志（开发模式），包含时间戳和字段。

### 2. JSON 日志模式验证

```powershell
$env:LOG_FORMAT="json"
.venv\Scripts\python -c "
from app.logging_config import setup_logging
import structlog
setup_logging()
log = structlog.get_logger()
log.info('test_json', action='verify')
"
```

**预期**：输出为单行 JSON 对象。

### 3. 请求日志验证

启动后端后发送请求：

```powershell
.venv\Scripts\uvicorn app.main:app --port 8080
# 另一个终端：
curl http://localhost:8080/api/health
curl -X POST http://localhost:8080/api/chat/stream -H "Content-Type: application/json" -d '{"message":"hello"}'
```

**预期**：后端终端显示 chat/stream 请求的 `http_request` 日志（含 elapsed_ms），health 请求不记录。

### 4. Docker 构建验证

```powershell
cd gas-copilot
docker-compose build
```

**预期**：两个镜像构建成功。

### 5. Docker 启动验证

```powershell
docker-compose up -d
# 检查状态
docker-compose ps
# 检查后端健康
curl http://localhost:8080/api/health
# 检查前端
# 浏览器打开 http://localhost:3000
```

### 6. LangSmith 追踪验证（需有 API Key）

在 `.env` 中设置 `LANGCHAIN_TRACING_V2=true` 和有效的 `LANGCHAIN_API_KEY`，重启后端，发送一条对话。

在 [smith.langchain.com](https://smith.langchain.com) → gas-copilot 项目中应看到一条完整的 trace 链路。

---

## 三、文件清单

| 文件 | 状态 | 说明 |
|------|:----:|------|
| `backend/app/logging_config.py` | 新增 | structlog 配置（开发彩色 / 生产 JSON） |
| `backend/app/main.py` | 修改 | 添加 `setup_logging()`、HTTP 请求日志中间件、启动信息增强 |
| `backend/.env.example` | 重写 | 清理真实密钥、增加分组注释、添加 LangSmith 和 LOG_FORMAT 说明 |
| `backend/Dockerfile` | 新增 | Python 3.12-slim + requirements-rag + uvicorn |
| `backend/.dockerignore` | 新增 | 排除 .venv、scripts、tests |
| `frontend/Dockerfile` | 新增 | 两阶段构建：Node 编译 + Nginx 托管 |
| `frontend/nginx.conf` | 新增 | SPA 路由 + `/api/` 反向代理到 backend |
| `frontend/.dockerignore` | 新增 | 排除 node_modules、dist |
| `docker-compose.yml` | 新增 | backend + frontend，数据卷持久化 |
| `.dockerignore` | 新增 | 根级排除 |
| `.gitignore` | 新增 | Python/Node/IDE/数据文件排除 |
| `README.md` | 新增 | 项目文档（功能、技术栈、快速开始、Docker、配置） |

---

## 四、架构总览（最终状态）

```
                          ┌──────────────────┐
                          │   浏览器客户端    │
                          └────────┬─────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            │ Docker Compose       │                      │
            │                      ▼                      │
            │  ┌─────────────────────────────────────┐    │
            │  │  frontend (nginx:alpine, :3000)     │    │
            │  │  SPA + /api/ → proxy → backend:8000 │    │
            │  └──────────────────┬──────────────────┘    │
            │                     │                       │
            │                     ▼                       │
            │  ┌─────────────────────────────────────┐    │
            │  │  backend (python:3.12-slim, :8080)  │    │
            │  │                                     │    │
            │  │  FastAPI + LangGraph Agent           │    │
            │  │  ├─ Planner (DeepSeek LLM)          │    │
            │  │  ├─ Tool Executor (5 工具)            │    │
            │  │  ├─ RAG Retriever (ChromaDB+BM25)    │    │
            │  │  ├─ Reflector                        │    │
            │  │  └─ Responder → SSE Stream           │    │
            │  │                                     │    │
            │  │  structlog JSON → stdout             │    │
            │  │  LangSmith trace → cloud (可选)      │    │
            │  └──────────────────┬──────────────────┘    │
            │                     │                       │
            │          ┌──────────┴──────────┐            │
            │          │  backend-data (vol)  │            │
            │          │  SQLite + ChromaDB   │            │
            │          └─────────────────────┘            │
            └─────────────────────────────────────────────┘
```

---

## 五、后续可选增强

- **日志采集**：Docker JSON 日志可接入 Loki/Promtail 或 ELK 做集中化分析
- **Prometheus 指标**：接入 `prometheus-fastapi-instrumentator` 暴露 `/metrics`
- **前端错误监控**：接入 Sentry 前端 SDK 捕获 JS 运行时异常
- **CI/CD**：GitHub Actions 构建镜像 + 推送至 Docker Registry
- **HTTPS**：在 nginx 层或 Traefik/Caddy 反向代理层配置 TLS 证书
