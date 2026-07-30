# assets/agents — 多 Agent 定义与协作协议

本目录是「编辑团队」的可部署资产。`references/craft/editorial-team.md` 是方法论，
本目录是让它真正跑起来的四个 agent 定义文件 + 部署/降级/防死循环协议。

## 文件清单

| 文件 | 角色 | 职责一句话 |
|---|---|---|
| `planning-editor.md` | 策划主编 | 读章纲/人物卡/追踪文件，产出 Chapter Brief 传给写作特工 |
| `novelist.md` | 写作特工 | 只接收 Brief，只输出 `NOVEL_TEXT_START...NOVEL_TEXT_END` 之间的纯正文 |
| `anti-ai-editor.md` | 反AI编辑 | 对正文执行 7 Gate 检测 + 两遍式润色，输出报告 + 净化后正文 |
| `consistency-reviewer.md` | 连载核实官 | 核查事实冲突/伏笔断线/角色属性一致性，输出 S1–S4 报告 |

每个 `.md` 文件带 frontmatter（`name:`/`description:`），可被 Claude Code / OpenCode
等支持项目级 agents 的工具直接加载；Codex CLI 需转成 `.toml`
（`name`/`description`/`developer_instructions` 三字段），或由主会话按文件内容内联扮演（solo 模式）。

## 部署

把四个 `.md` 文件拷入目标环境的项目级 agents 目录：

```bash
# Claude Code / OpenCode（项目级）
cp assets/agents/*.md {书籍工程根}/.claude/agents/

# TRAE（项目级）
cp assets/agents/*.md {书籍工程根}/.trae/agents/

# Codex CLI 需转成 .toml（name/description/developer_instructions 三字段），
# 或直接由主会话按本目录文件内容内联扮演（solo 模式）。
```

部署后新开会话，由主 Agent（总编辑）在编辑团队流程中按 `editorial-team.md`
的 spawn 协议调用。

## 模型分级建议（成本与质量平衡）

| Agent | 建议档位 | 理由 |
|---|---|---|
| planning-editor | 高（旗舰/Opus 级） | Chapter Brief 质量决定本章上限，值得用好模型 |
| novelist | 高（旗舰/Opus 级） | 正文质量是核心产出 |
| anti-ai-editor | 中（Sonnet 级） | 7 Gate 是模式识别活，中档足够 |
| consistency-reviewer | 低（Haiku 级） | 一致性核查是比对活，便宜模型即可，还能省出每章都查的成本 |

## Fallback 链（spawn 前必查）

按以下顺序判定，**任何一级不满足就降级，不强行 spawn**：

1. 检查项目 agents 目录（`.claude/agents/` → `.trae/agents/` → `.opencode/agents/` → `.codex/agents/`）：
   对应文件存在且 frontmatter 的 `name:` 与目标 agent 一致 → 可用。
2. 任一 agent 缺失/文件损坏 → 该角色降级为「主会话内联扮演」
   （用对应 .md 文件的内容作为 prompt 切换视角），报告中注明 `Fallback: missing {agent} -> solo`。
3. spawn 调用本身失败 → 同样降级 solo，注明 `Fallback: spawn failed -> solo`。
4. 全部 agent 不可用时，整个编辑团队流程退化为 `chapter-loop.md` 单 Agent 循环，
   机器闸口（`check_text.py` + `rhythm_guard.py`）照常——**机器闸口不依赖任何 agent，
   是质量底线，永远可用**。

## 防死循环协议（总编辑必须执行）

多轮审核最危险的失控是「改了审、审了改」无限循环。硬规则：

1. **单章返工上限 2 次**：P0 触发的重写最多 2 轮；第 2 轮仍有 P0 → 停止，
   把争议点列给作者裁决，不再自动返工。
2. **连续 3 章「有条件通过」→ 强制人工介入**：说明系统性问题（多半是纲或
   设定的问题，不是单章问题），暂停日更，向作者汇报并给出根因分析。
3. **审核不迭代**：consistency-reviewer 与 anti-ai-editor 每章各跑一次，
   不因为「报告不满意」让同一角色重审同一章——分歧由总编辑裁决。
4. **budget 提醒**：编辑团队流程 token 消耗约为单 Agent 循环的 3–4 倍，
   日常日更走单 Agent 循环，关键章（卷末高潮/大反转/上架前）才启用团队。

## 与脚本的协作（v2.1）

编辑团队不取代机器闸口，而是与 `scripts/` 下的工具协同。团队流程的关键节点都对接了脚本：

| 流程节点 | 用哪个脚本 | 作用 |
|---|---|---|
| 团队启动前确认无欠账 | `scripts/resume.py "{书}"` | 欠账未清禁止启动团队写新章（铁律第 1 条） |
| 确认上一章门禁已清 | `scripts/check_text.py {章} --verify-prev` | 上一章门禁未过则不开新章 |
| 7 Gate 检测（反AI编辑可调用） | `scripts/check_text.py {章} --gate-report` | 机器查七类，agent 看报告定性 |
| 节奏配额检查 | `scripts/rhythm_guard.py --chapter-file {章} --quota {配额}` | 越界/冷却违规机器先报 |
| 标点归一化（可选，润色前后均可跑） | `scripts/normalize_punct.py {章}` | 清理非功能性标点，减少 anti-ai-editor 的无效命中 |
| 追踪五文件回写后校验 | `scripts/validate_tracking.py "{书}"` | 防 agent 把追踪格式写歪，让下游脚本静默漏检 |
| 重建实体索引 | `scripts/entity_index.py build "{书}"` | 让下一章的策划主编能查实体定位章节 |
| 文风漂移检测（可选） | `scripts/style_fingerprint.py compare {章} {文风锚}` | anti-ai-editor 判断腔调是否漂移的量化依据 |

**机器闸口是底线，agent 是增量**：`check_text.py` + `rhythm_guard.py` 任何时候都能跑，
不依赖 agent 是否部署；`anti-ai-editor` 与 `consistency-reviewer` 是在机器闸口之上
加一层语义判断（情绪展示是否到位、伏笔回收细节是否对得上埋设细节等）。

## 开书与恢复的对接

- **新建书籍工程**用 `scripts/init_book.py "{书名}" --genre {} --platform {}` 一键建骨架，
  agents 部署到生成出来的 `{书名}/.claude/agents/`（或对应工具目录）。
- **会话恢复**用 `scripts/resume.py "{书}"` 在团队流程开始前确认无欠账，
  退出码 1（有欠账）时不启动团队，先补账。

## 状态查询

主会话可以用 `scripts/resume.py {书}` 在团队流程开始前确认无欠账；
用 `scripts/check_text.py {章} --verify-prev` 确认上一章门禁已清——
欠账未清时禁止启动团队写新章（铁律第 1 条）。

## 模型分层体系（v2.1 新增）

### 分层定义

| 分层 | 代号 | 代表模型 | 定位 |
|---|---|---|---|
| 旗舰层 | T0 | Claude Opus 4 / GPT-4o | 最强推理，用于复杂规划与预算计算 |
| 主力层 | T1 | Claude Sonnet 4 / GPT-4o-mini | 创意生成+模式匹配，质量与成本平衡 |
| 效率层 | T2 | Claude Haiku / GPT-4o-mini | 规则检查+事实核查，高吞吐低成本 |

### 各 Agent 分层配置

| Agent | 推荐模型 | 分层 | 分层理由 |
|---|---|---|---|
| planning-editor | claude-opus-4-20250514 | T0 | 章纲规划、情节点预算计算、节奏配额核查需要复杂多步推理和数值计算 |
| novelist | claude-sonnet-4-20250514 | T1 | 创意生成和文风控制，不需要旗舰级推理，T1 在创意质量和成本间最佳平衡 |
| anti-ai-editor | claude-sonnet-4-20250514 | T1 | 模式识别和文本改写，对语言理解有较高要求但不需要旗舰级推理 |
| consistency-reviewer | claude-haiku-4-20250514 | T2 | 规则检查和事实核查为主，不涉及创意生成，T2 即可胜任 |

### 降级协议

- 当推荐模型不可用时，可降级到下一层模型（T0 -> T1 -> T2）
- 降级后需增加人工复核步骤
- T2 Agent 不建议降级到更低层（已是最低）
- 如 T2 不可用，建议暂停编辑团队流程，改为单 Agent 模式

### 与已有「模型分级建议」的关系

上文的「模型分级建议」是初始概览；本节是正式的分层体系定义。
各 Agent `.md` 文件的 frontmatter 中包含 `recommended_model` 和 `model_tier`
两个字段，可被部署工具直接读取。两节信息一致，本节作为集中参考。
