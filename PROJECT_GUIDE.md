# MiroFish Project Guide (Refactored "Free Plan" Architecture)

> **Status:** Refactored (v2.0 - Local JSON + Mem0 REST)  
> **Last Updated:** 2026-02-11  
> **Maintainer:** Backend Team

---

## 1. 项目概览 (Project Overview)

**MiroFish** 是一个基于 AI 的个人知识库与图谱构建系统。它能够读取用户上传的非结构化文本（如 PDF、TXT），通过大模型（LLM）提取实体与关系，构建可视化的知识图谱，并提供基于语义的智能问答功能。

本项目旨在为个人开发者提供一个**低成本、零运维负担**的解决方案。

---

## 2. 本次重构目标与边界 (Refactoring Goals)

为了降低部署难度并移除对重型云服务（Zep Cloud）的依赖，我们对后端架构进行了深度重构，实现了 **"Free Plan"** 架构。

### 核心变更
1.  **移除 Zep Cloud**: 不再依赖 Zep 进行图谱存储和检索。
2.  **双管道架构 (Dual Pipeline)**:
    *   **Pipeline A (Semantic Memory)**: 使用 **Mem0 Cloud** (通过 REST API) 存储文本块的向量索引，用于语义搜索。
    *   **Pipeline B (Knowledge Graph)**: 使用 **Local JSON** 文件存储图谱的节点（Node）和边（Edge）结构，用于前端 D3.js 可视化。
3.  **移除 Mem0 SDK**: 为了避免 `mem0` Python SDK 强制依赖 OpenAI SDK 导致的 `LLM_API_KEY` (DashScope/Qwen) 冲突问题，我们移除了 `mem0` SDK，转而实现了轻量级的 `Mem0Client` (REST based)。

---

## 3. 端到端业务流程 (End-to-End Flow)

### 3.1 图谱构建流程 (`/api/graph/build`)

当用户上传文件并点击“生成图谱”时，后端 `GraphBuilderService` 会并行触发两条流水线：

```mermaid
graph TD
    User[用户请求 /api/graph/build] --> API[Graph API]
    API --> Builder[GraphBuilderService]
    
    subgraph "Pipeline A: 语义记忆 (Mem0 Cloud)"
    Builder -- 1. 文本分块 --> Chunk[Text Chunks]
    Chunk -- 2. REST API (Add) --> Mem0[Mem0 Cloud]
    Mem0 -- 3. 存储向量 --> VectorDB[(Vector Store)]
    end
    
    subgraph "Pipeline B: 知识图谱 (Local JSON)"
    Builder -- 1. LLM 提取实体/关系 --> Extraction[Entity Extraction (Qwen-Plus)]
    Extraction -- 2. 构建图结构 --> LocalStore[LocalGraphStore]
    LocalStore -- 3. 写入文件 --> JSON[(backend/data/graphs/{id}.json)]
    end
    
    JSON --> D3[前端 D3.js 渲染]
```

### 3.2 搜索与问答流程 (`/api/chat` 或工具调用)

1.  **语义检索**: 调用 `Mem0Client.search(query)` 从 Mem0 Cloud 获取相关的文本片段。
2.  **图谱检索**: (可选) 读取本地 JSON 加载图结构。
3.  **生成回答**: LLM 结合检索到的上下文生成最终回复。

---

## 4. 目录结构总览 (Directory Structure)

仅列出核心后端文件：

```text
backend/
├── app/
│   ├── api/
│   │   ├── graph.py            # [API] 图谱构建入口，包含详细的错误堆栈日志
│   │   └── ...
│   ├── core/
│   │   └── config.py           # [Config] 环境变量加载
│   ├── services/
│   │   ├── graph_builder.py    # [Core] 图谱构建核心编排 (Pipeline A & B)
│   │   ├── graph_tools.py      # [Tool] 搜索与报表工具，调用 Mem0Client
│   │   ├── local_graph_store.py# [Store] 本地 JSON 图谱存取逻辑
│   │   ├── mem0_client.py      # [Client] 自研 Mem0 REST 客户端 (替代 SDK)
│   │   ├── entity_reader.py    # [Helper] 简单的实体读取适配器
│   │   └── ...
│   └── ...
├── data/
│   └── graphs/                 # [Data] 存放生成的图谱 JSON 文件
│       └── {graph_id}.json
├── requirements.txt            # 依赖列表 (新增 requests, 移除 zep-cloud)
└── ...
```

---

## 5. 【重构重点】模块详解 (Key Modules)

### 5.1 `Mem0Client` (`backend/app/services/mem0_client.py`)
这是本次重构的核心组件。它是一个纯 Python `requests` 实现的客户端，用于与 `api.mem0.ai` 通信。

*   **设计初衷**: 解决 `mem0` SDK 强制检查 `OPENAI_API_KEY` 的问题，兼容 DashScope (`qwen-plus`)。
*   **主要方法**:
    *   `add(messages, user_id)`: 上传文本块到 Mem0。
    *   `search(query, user_id)`: 执行语义搜索。
    *   `delete_all(user_id)`: 清空用户记忆。
*   **容错性**: 如果 Mem0 API 调用失败（如网络超时），它会记录 Error 日志但**不会抛出异常**，确保 Pipeline B（本地图谱构建）能继续完成。

### 5.2 `GraphBuilderService` (`backend/app/services/graph_builder.py`)
协调者服务。

*   **`build_graph`**: 入口方法，负责读取文件内容。
*   **`_build_graph_worker`**: 异步工作线程。
    *   **步骤 1**: 初始化 `LocalGraphStore`。
    *   **步骤 2 (Pipeline A)**: 调用 `Mem0Client` 将文本存入云端。此步骤包含 `try-except` 保护，失败仅打印警告。
    *   **步骤 3 (Pipeline B)**: 调用 LLM 提取实体，构建 `nx.Graph`，并通过 `LocalGraphStore` 保存为 JSON。

### 5.3 `LocalGraphStore` (`backend/app/services/local_graph_store.py`)
负责图谱数据的持久化。

*   **存储路径**: `backend/data/graphs/{graph_id}.json`。
*   **数据格式**: 标准的 NetworkX node-link data 格式。
    ```json
    {
      "nodes": [{"id": "Entity1", "type": "Person", ...}],
      "links": [{"source": "Entity1", "target": "Entity2", "relation": "Knows", ...}]
    }
    ```

---

## 6. 环境变量与配置 (Configuration)

在 `.env` 文件中必须配置以下关键变量：

| 变量名 | 说明 | 示例值 |
| :--- | :--- | :--- |
| `LLM_API_KEY` | **DashScope (阿里云)** API Key，用于图谱提取 | `sk-xxx` |
| `LLM_MODEL` | 使用的模型名称 | `qwen-plus` |
| `MEM0_API_KEY` | **Mem0 Cloud** API Key，用于语义记忆 | `m0-xxx` |

> **注意**: 严禁设置 `OPENAI_API_KEY`，除非你确实在使用 OpenAI 的服务。本项目默认使用 DashScope。

---

## 7. 安装与启动 (Installation & Startup)

### 7.1 环境准备
确保 Python 3.10+ 环境。

```bash
cd backend
# 1. 安装依赖 (确保已包含 requests)
pip install -r requirements.txt
```

### 7.2 启动服务
```bash
# 开发模式启动
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## 8. 验收清单 (Acceptance Checklist)

新功能开发或部署后，请按以下步骤验证：

1.  **检查配置**: 确认 `.env` 中 `LLM_API_KEY` 和 `MEM0_API_KEY` 已正确设置。
2.  **构建图谱**:
    *   发送 `POST /api/graph/build` 请求（附带文件）。
    *   **预期结果**: 接口立即返回 `200 OK`，后台开始异步处理。
3.  **验证日志**:
    *   查看控制台输出，确认没有 `Traceback`。
    *   确认出现 `[Mem0Client] Successfully added ...` (Pipeline A 成功)。
    *   确认出现 `Graph saved to ...` (Pipeline B 成功)。
4.  **验证产物**:
    *   检查 `backend/data/graphs/` 目录下是否生成了新的 `.json` 文件。
    *   检查该 JSON 文件内容是否包含 `nodes` 和 `links`。
5.  **验证搜索**:
    *   调用相关搜索接口或工具，确认能返回基于 Mem0 的搜索结果。

---

**MiroFish Team**
