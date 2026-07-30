# long-novel-skill MCP Server

将小说创作技能封装为MCP Server，支持任何MCP客户端（Claude Desktop、TRAE、Cursor、VS Code、Continue等）调用。

## 快速开始

### 安装依赖

```bash
pip install mcp
```

### 启动Server

**stdio模式（默认，推荐本地集成）**:
```bash
cd mcp_server
python server.py
```

**HTTP模式（远程服务）**:
```bash
cd mcp_server
python server.py --http --port 8000
```

### 配置MCP客户端

#### Claude Desktop
在 `claude_desktop_config.json` 中添加：
```json
{
  "mcpServers": {
    "long_novel_skill": {
      "command": "python",
      "args": ["D:/path/to/long-novel-skill/mcp_server/server.py"]
    }
  }
}
```

#### Cursor
在 `.cursor/mcp.json` 或全局设置中添加：
```json
{
  "mcpServers": {
    "long_novel_skill": {
      "command": "python",
      "args": ["D:/path/to/long-novel-skill/mcp_server/server.py"]
    }
  }
}
```

#### TRAE
在 `.trae/mcp.json` 中添加：
```json
{
  "mcpServers": {
    "long_novel_skill": {
      "command": "python",
      "args": ["D:/path/to/long-novel-skill/mcp_server/server.py"]
    }
  }
}
```

#### VS Code + Cline
在Cline设置中添加：
```json
{
  "mcpServers": [
    {
      "name": "long_novel_skill",
      "command": "python",
      "args": ["D:/path/to/long-novel-skill/mcp_server/server.py"]
    }
  ]
}
```

## 工具列表（26个）

| 工具名 | 功能 | 只读 | 破坏性 |
|--------|------|------|--------|
| `novel_check_text` | 7 Gate质量检查 | 是 | 否 |
| `novel_style_fingerprint` | 文风指纹提取 | 是 | 否 |
| `novel_rhythm_guard` | 节奏守卫检查 | 是 | 否 |
| `novel_deconstruct` | 拆文分析 | 是 | 否 |
| `novel_outline_anchor` | 大纲锚点管理 | 否 | 否 |
| `novel_event_matrix` | 事件矩阵管理 | 否 | 否 |
| `novel_entity_index` | 实体索引管理 | 否 | 否 |
| `novel_story_graph` | 知识图谱管理 | 否 | 否 |
| `novel_research` | 联网调研 | 否 | 否 |
| `novel_style_library` | 风格库管理 | 否 | 否 |
| `novel_content_expander` | 智能内容扩充 | 是 | 否 |
| `novel_context_manager` | 上下文管理 | 是 | 否 |
| `novel_flow` | 小说流程编排 | 否 | 否 |
| `novel_quality_score` | 质量评分 | 是 | 否 |
| `novel_beat_sheet` | Beat Sheet生成 | 否 | 否 |
| `novel_chapter_synthesizer` | 章节合成 | 否 | 否 |
| `novel_gate_repair` | 门禁修复 | 是 | 否 |
| `novel_editorial_manager` | 编辑团队管理 | 否 | 否 |
| `novel_hooks` | 自动化Hook | 否 | 否 |
| `novel_rag_retriever` | RAG检索增强 | 是 | 否 |
| `novel_init_book` | 初始化书籍工程 | 否 | 是 |
| `novel_resume` | 会话恢复 | 是 | 否 |
| `novel_normalize_punct` | 标点归一化 | 否 | 否 |
| `novel_validate_tracking` | 追踪文件验证 | 是 | 否 |

## 使用示例

### 质量检查
调用 `novel_check_text` 检查章节：
```json
{
  "file_path": "./正文/第001章_开局.md",
  "min_chars": 2000,
  "max_chars": 3500,
  "gate_report": true
}
```

### 初始化书籍
调用 `novel_init_book` 创建新项目：
```json
{
  "title": "我的修仙传",
  "genre": "玄幻",
  "platform": "番茄"
}
```

### 文风提取
调用 `novel_style_fingerprint` 提取文风：
```json
{
  "book_dir": "./我的修仙传",
  "chapters": "1-5"
}
```

## 与Skill格式的关系

- **MCP Server**: 提供可编程工具接口，任何MCP客户端都能调用
- **SKILL.md**: 提供AI Agent工作流指令，指导Agent何时/如何调用工具
- **最佳实践**: 同时配置MCP Server（能力层）和Skill（知识层），获得完整体验
