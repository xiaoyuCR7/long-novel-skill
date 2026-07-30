# 门禁产物规范（Gate Artifacts Specification）

本文档定义每章写完后的门禁产物 schema、存放路径、命名约定，以及跨 Agent 消费门禁
产物的接口规范。是 `check_text.py`、`rhythm_guard.py`、`pacing-review.md`、
`consistency_report.md` 等门禁组件的唯一权威产物规范。

## 一、门禁总览

每章写完后的完整门禁流程（按顺序）：

```
标点归一化 → check_text.py（7 Gate）→ rhythm_guard.py（节奏配额）→
语义级节奏审查（pacing-review.md）→ 一致性审查（consistency_report.md）→
自查清单 → 门禁综合判定
```

每步产出对应的门禁产物，统一存入 `追踪/门禁/` 目录。

## 二、门禁产物存放路径约定

所有门禁产物以 `追踪/门禁/` 为根目录，章号使用三位数补零格式：

```
{书籍工程}/
└── 追踪/
    └── 门禁/
        ├── gate_ch{N}.json          # 门禁综合状态（JSON，机器可读）
        ├── check_ch{N}.json         # 7 Gate 检查详细结果（check_text.py 产出）
        ├── rhythm_ch{N}.json        # 节奏配额检查结果（rhythm_guard.py 产出）
        ├── pacing_review_ch{N}.md   # 语义级节奏审查报告（人工/Agent 产出）
        ├── consistency_ch{N}.md     # 一致性审查报告（consistency-reviewer 产出）
        └── anti_ai_ch{N}.md         # 去AI味自查报告（人工/Agent 产出，可选）
```

**路径约定**：
- `{N}` 为章号，使用阿拉伯数字，不补零。如第 5 章：`gate_ch5.json`，第 37 章：`gate_ch37.json`。
- 文件名不含章节标题，仅含章号。
- 所有门禁产物均为持久化文件，不是临时产物，跨会话保留。

## 三、gate_ch{N}.json — 门禁综合状态

### 用途

`gate_ch{N}.json` 是每章门禁的「唯一真相源」——汇聚所有子门禁的检查结果，
由 `check_text.py` 的 `--gate-report` 模式首次创建，后续由 `rhythm_guard.py`
的 `--gate-state` 模式合并节奏检查结果，再由 pacing-review 和 consistency-review
追加语义审查结果。

### 完整 Schema

```json
{
  "chapter": 37,
  "book": "仙道长青",
  "created_at": "2026-07-28T15:30:00",
  "updated_at": "2026-07-28T15:35:00",
  "passed": true,
  "fail_reason": null,
  "scores": {
    "overall": 0.92,
    "text_check": 0.95,
    "rhythm": 1.0,
    "pacing": 0.9,
    "consistency": 0.85
  },
  "checks": {
    "text_check": { "...": "见下方 check_text 段" },
    "rhythm": { "...": "见下方 rhythm 段" },
    "pacing_review": { "...": "见下方 pacing_review 段" },
    "consistency": { "...": "见下方 consistency 段" }
  },
  "chapter_file": "正文/第037章_宗门大比.md",
  "chapter_mtime": "2026-07-28T15:20:00"
}
```

### 字段规范

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `chapter` | int | 是 | 章号 |
| `book` | string | 否 | 书名（从书籍工程目录名推断） |
| `created_at` | string | 是 | 门禁首次创建时间（ISO 8601，精确到秒） |
| `updated_at` | string | 是 | 门禁最后更新时间（每次合并子门禁结果时更新） |
| `passed` | bool | 是 | 本章门禁是否全部通过。**任一子门禁 `passed=false` 则此处为 false。** |
| `fail_reason` | string\|null | 是 | 若 `passed=false`，此处列出失败原因（一句话摘要）。若 `passed=true`，此处为 null。 |
| `scores` | object | 是 | 各子门禁的量化分数（0.0-1.0），含 `overall` 加权总分 |
| `checks` | object | 是 | 各子门禁的详细结果摘要（只存摘要，完整结果在各自产物文件中） |
| `chapter_file` | string | 是 | 本章正文文件的相对路径（相对于书籍工程根目录） |
| `chapter_mtime` | string | 是 | 本章正文文件的最后修改时间（ISO 8601），用于跨会话「正文写后是否改动」查验 |

### returned 判定逻辑

`passed` 字段的判定逻辑（按优先级）：

1. 若 `checks.text_check.passed == false` → `passed = false`
2. 若 `checks.rhythm.passed == false` → `passed = false`
3. 若 `checks.pacing_review.passed == false` → `passed = false`
4. 若 `checks.consistency.passed == false` → `passed = false`
5. 以上全部通过 → `passed = true`

### scores 加权规则

`overall` 分数的加权公式：

```
overall = text_check * 0.35 + rhythm * 0.25 + pacing * 0.25 + consistency * 0.15
```

- `text_check` 权重最高（0.35）：字数/禁用词/毒句式/AI 腔是基础门槛，不通过其他无从谈起。
- `rhythm` 与 `pacing` 并列（各 0.25）：节奏配额+语义节奏是章节质量的核心。
- `consistency` 权重最低（0.15）：一致性审查是增量检查，已有其他门禁兜底。

### 跨会话查验

`resume.py` 和 `check_text.py --verify-prev` 读取 `gate_ch{N}.json` 时，
执行以下查验：

1. **文件存在性**：`追踪/门禁/gate_ch{N}.json` 不存在 → 门禁未执行，FAIL。
2. **passed 状态**：`passed == false` → 门禁未通过，FAIL。
3. **mtime 一致性**：`chapter_mtime` 与当前正文文件的 mtime 不一致 → 正文写后改动，FAIL。
4. 以上三项全部通过 → 门禁有效，进入下一章。

## 四、check_text 段 — 7 Gate 检查结果

### 存放位置

`check_text.py` 的 `--gate-report` 模式将详细结果写入 `追踪/门禁/check_ch{N}.json`，
同时在 `gate_ch{N}.json` 的 `checks.text_check` 段写入摘要。

### gate_ch{N}.json 中的 checks.text_check 摘要

```json
{
  "checks": {
    "text_check": {
      "passed": true,
      "failed_items": 0,
      "warn_items": 2,
      "word_count": 2847,
      "word_count_pass": true,
      "banned_words_hits": 0,
      "toxic_patterns_hits": 0,
      "ai_pattern_hits": 1,
      "foreshadowing_overdue": 0,
      "deslop_score": 0.12,
      "deslop_grade": "轻",
      "verified_at": "2026-07-28T15:30:00"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `passed` | bool | 7 Gate 是否全部通过（不含 advisory 级别） |
| `failed_items` | int | blocking 级别的命中数量 |
| `warn_items` | int | advisory 级别的命中数量 |
| `word_count` | int | 本章正文字数（非空白字符数） |
| `word_count_pass` | bool | 字数是否在上下限区间内 |
| `banned_words_hits` | int | 禁用词命中次数 |
| `toxic_patterns_hits` | int | 毒句式命中次数 |
| `ai_pattern_hits` | int | AI 模式检测命中次数（7 类段落级检测） |
| `foreshadowing_overdue` | int | 伏笔超期数量（需 --ledger 参数） |
| `deslop_score` | float | AI 味量化分数（0.0-1.0，越低越好） |
| `deslop_grade` | string | AI 味分级：轻/中/重 |
| `verified_at` | string | 检查时间（ISO 8601） |

### check_ch{N}.json 完整结果

`check_ch{N}.json` 包含 `check_text.py` 的全部输出，格式由 `check_text.py` 的
`--gate-report` 模式定义，此处不重复。Agent 消费时优先读 `gate_ch{N}.json` 的
摘要段，需要详细命中信息时再读 `check_ch{N}.json`。

## 五、rhythm 段 — 节奏配额检查结果

### 存放位置

`rhythm_guard.py` 的 `--gate-state` 模式将结果合并到 `gate_ch{N}.json` 的
`checks.rhythm` 段。完整结果不单独存文件（rhythm 检查结果结构简单，全量存入
gate 综合状态即可）。

### Schema

```json
{
  "checks": {
    "rhythm": {
      "passed": true,
      "fails": [],
      "warns": ["慢档缺失：近4章无慢档"],
      "declare": "配额 A，事件 conflict，档位 快",
      "checked_at": "2026-07-28T15:31:00"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `passed` | bool | 节奏配额检查是否通过（无 FAIL 项） |
| `fails` | string[] | 违规项列表（每项为一条中文描述） |
| `warns` | string[] | 警告项列表（每项为一条中文描述） |
| `declare` | string | 本章的节奏声明（配额/事件/档位） |
| `checked_at` | string | 检查时间（ISO 8601） |

### 与 gate_ch{N}.json 的合并策略

`rhythm_guard.py --gate-state` 执行时：
1. 读取 `gate_ch{N}.json`（如存在）
2. 设置 `checks.rhythm` 段
3. 更新 `updated_at`
4. 重新计算 `passed` 和 `scores.rhythm`（rhythm 的分数：passed=true → 1.0，否则 `1.0 - 0.3 * len(fails) - 0.1 * len(warns)`，最低 0.0）
5. 重新计算 `scores.overall`
6. 写回 `gate_ch{N}.json`

## 六、pacing_review 段 — 语义级节奏审查

### 存放位置

语义级节奏审查的完整报告写入 `追踪/门禁/pacing_review_ch{N}.md`（格式见
`references/craft/pacing-review.md` 的「审查产物格式」一节）。

同时在 `gate_ch{N}.json` 的 `checks.pacing_review` 段写入摘要。

### gate_ch{N}.json 中的 checks.pacing_review 摘要

```json
{
  "checks": {
    "pacing_review": {
      "passed": true,
      "conclusion": "通过",
      "gear_consistency": "一致",
      "quota_violation": false,
      "quota_fraud": false,
      "suspense_grade": "强",
      "hidden_acceleration": false,
      "issues": [],
      "reviewed_at": "2026-07-28T15:33:00"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `passed` | bool | 语义级节奏审查是否通过 |
| `conclusion` | string | 审查结论：通过/有条件通过/失败 |
| `gear_consistency` | string | 档位一致性：一致/不一致（{说明}） |
| `quota_violation` | bool | 是否触发 A/B/C 配额越界（同时 ≥2 项） |
| `quota_fraud` | bool | 是否存在配额欺诈（章纲声明与实际不符） |
| `suspense_grade` | string | 章末悬念等级：强/中/弱/无 |
| `hidden_acceleration` | bool | 是否存在隐性加速（场景跳跃/时间跳跃缩略/情绪跳跃/信息密度异常/对抗缺失） |
| `issues` | string[] | 具体问题列表（每项为一条中文描述）。通过时为空数组。 |
| `reviewed_at` | string | 审查时间（ISO 8601） |

### 与 pacing_review_ch{N}.md 的关系

`pacing_review_ch{N}.md` 是完整报告（含四维度逐一分析、判断依据、整改建议），
`gate_ch{N}.json` 中的 `pacing_review` 段是摘要（只含结论性字段）。

Agent 消费时：
- 快速判断门禁状态 → 读 `gate_ch{N}.json` 的 `pacing_review.passed`
- 需要了解具体问题 → 读 `pacing_review_ch{N}.md`

## 七、consistency 段 — 一致性审查

### 存放位置

一致性审查的完整报告写入 `追踪/门禁/consistency_ch{N}.md`。

同时在 `gate_ch{N}.json` 的 `checks.consistency` 段写入摘要。

### gate_ch{N}.json 中的 checks.consistency 摘要

```json
{
  "checks": {
    "consistency": {
      "passed": true,
      "ooc_count": 0,
      "foreshadowing_issues": 0,
      "timeline_issues": 0,
      "entity_conflicts": 0,
      "cross_chapter_issues": 0,
      "issues": [],
      "reviewed_at": "2026-07-28T15:35:00"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `passed` | bool | 一致性审查是否通过 |
| `ooc_count` | int | 角色 OOC（Out of Character）问题数量 |
| `foreshadowing_issues` | int | 伏笔一致性问题数量 |
| `timeline_issues` | int | 时间线一致性问题数量 |
| `entity_conflicts` | int | 实体冲突数量（同一实体在不同章的定义不一致） |
| `cross_chapter_issues` | int | 跨章节一致性问题数量 |
| `issues` | object[] | 具体问题列表，每条含 `{type, severity, description, chapters}` |
| `reviewed_at` | string | 审查时间（ISO 8601） |

### issues 数组元素 Schema

```json
{
  "type": "ooc",
  "severity": "P1",
  "description": "第37章中林晚晴主动出手相救，与角色卡「冷漠疏离、不主动介入他人事务」矛盾",
  "chapters": [37],
  "related_chapters": [12, 25],
  "recommendation": "修改本章林晚晴的行为动机：可以是被迫卷入而非主动出手"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | string | 问题类型：ooc/foreshadowing/timeline/entity/cross_chapter |
| `severity` | string | 严重度：P0（阻断）/P1（高）/P2（中）/P3（低） |
| `description` | string | 问题描述 |
| `chapters` | int[] | 涉及章节 |
| `related_chapters` | int[] | 关联章节（如角色卡引用章节、伏笔埋设章节） |
| `recommendation` | string | 修复建议 |

### consistency_ch{N}.md 的格式

```markdown
# 一致性审查报告 — 第{N}章

## 一、角色一致性
- **OOC 问题**：{数量} 项
- **详情**：[逐项列出]

## 二、伏笔一致性
- **问题**：{数量} 项
- **详情**：[逐项列出]

## 三、时间线一致性
- **问题**：{数量} 项
- **详情**：[逐项列出]

## 四、实体一致性
- **问题**：{数量} 项
- **详情**：[逐项列出]

## 五、跨章节一致性
- **问题**：{数量} 项
- **详情**：[逐项列出]

## 综合结论
- **一致性审查**：[通过/失败]
- **失败原因**：[若失败，列出具体原因]
- **整改建议**：[若失败，列出具体整改步骤]
```

## 八、与各脚本/Agent 的协作关系

### check_text.py

```
check_text.py --gate-report --gate-state
```

- **产出**：`check_ch{N}.json`（完整结果）+ `gate_ch{N}.json`（首次创建，含 text_check 段）
- **依赖**：正文文件、题材专属禁用词（`设定/禁用词.txt`）、伏笔台账（可选）
- **门禁状态落盘**：首次创建 `gate_ch{N}.json` 时设置 `created_at`、`chapter_file`、`chapter_mtime`
- **跨会话查验**：`--verify-prev` 模式读取 `gate_ch{N-1}.json` 的 `passed` 和 `chapter_mtime`

### rhythm_guard.py

```
rhythm_guard.py --chapter-file "正文/第XXX章.md" --quota "追踪/节奏配额.md" --gate-state
```

- **产出**：合并 `checks.rhythm` 段到 `gate_ch{N}.json`
- **依赖**：`gate_ch{N}.json` 已由 `check_text.py` 创建
- **合并策略**：读取 → 更新 rhythm 段 → 重新计算 `passed`/`scores` → 写回

### pacing-review.md（语义级节奏审查，人工/Agent 执行）

- **产出**：`pacing_review_ch{N}.md`（完整报告）+ 合并 `checks.pacing_review` 段到 `gate_ch{N}.json`
- **执行时机**：`check_text.py` 和 `rhythm_guard.py` 之后
- **依赖**：正文文件、章纲、`gate_ch{N}.json` 中的 `rhythm.declare`
- **合并策略**：与 `rhythm_guard.py` 相同——读取 `gate_ch{N}.json` → 更新 `pacing_review` 段 → 重新计算 `passed`/`scores` → 写回

### consistency-reviewer（一致性审查，Agent 执行）

- **产出**：`consistency_ch{N}.md`（完整报告）+ 合并 `checks.consistency` 段到 `gate_ch{N}.json`
- **执行时机**：`pacing-review` 之后、自查清单之前
- **依赖**：正文文件、人物卡、角色状态、伏笔台账、时间线、实体索引
- **合并策略**：与 `pacing_review` 相同

### resume.py

```
python scripts/resume.py "{书名目录}"
```

- **读取**：`gate_ch{N}.json`（最新章的 `passed`、`chapter_mtime`）
- **查验**：门禁是否通过 + 正文是否写后改动
- **不写入**：`resume.py` 只读门禁产物，不修改

## 九、跨 Agent 消费门禁产物的接口约定

### 接口一：读取门禁状态

**消费者**：任何需要判断「本章是否通过门禁」的 Agent。

**方法**：读取 `追踪/门禁/gate_ch{N}.json`，检查 `passed` 字段。

```
约束：
- passed=true  → 可以进入下一章
- passed=false → 必须修复问题后重新跑门禁
- 文件不存在  → 门禁未执行，禁止进入下一章
```

**二级消费**：读取各 `checks.*.passed` 判断具体哪个子门禁失败。

### 接口二：读取门禁详细结果

**消费者**：需要了解具体失败原因以进行修复的 Agent。

**方法**：
- 7 Gate 详情 → 读 `check_ch{N}.json`
- 节奏配额详情 → 读 `gate_ch{N}.json` 的 `checks.rhythm` 段（全量在此）
- 语义节奏详情 → 读 `pacing_review_ch{N}.md`
- 一致性详情 → 读 `consistency_ch{N}.md`

### 接口三：跨会话欠账查验

**消费者**：新会话开始时，`resume.py` 或 `check_text.py --verify-prev`。

**方法**：
1. 读取 `gate_ch{N-1}.json`（上一章的 gate 文件）
2. 检查 `passed` 是否为 true
3. 检查 `chapter_mtime` 是否与正文文件当前 mtime 一致
4. 任一不满足 → 判为「欠账」，要求先修复再开写

**注意**：跨会话查验只查上一章（N-1），不追溯更早的章——因为更早的章
在当时的会话中已经通过了门禁，且已进入下一章写作。只有最新完成的章
需要保证「门禁通过 + 写后未改动」。

### 接口四：门禁产物完整性校验

**消费者**：`validate_tracking.py`（追踪格式校验）。

**方法**：检查 `追踪/门禁/` 目录下是否存在对应章号的所有必需产物：
- `gate_ch{N}.json`（必须存在）
- `check_ch{N}.json`（必须存在，由 `check_text.py` 产出）
- `pacing_review_ch{N}.md`（关键章必须存在，日常章可选）
- `consistency_ch{N}.md`（关键章必须存在，日常章可选）

关键章定义：卷末章、高潮章、大反转章、身份揭晓章、上架章。

### 接口五：门禁产物消费防死循环

**问题场景**：Agent A 读取门禁 → 发现问题 → 修复 → 触发 Agent B 重新审查 → 
Agent B 发现问题 → 修复 → 触发 Agent A 重新审查 → ...

**防护机制**：
1. 每次门禁 `updated_at` 更新时，记录 `update_count`（更新次数）
2. 若 `update_count >= 3`（同一章门禁被更新 3 次以上），暂停自动修复，
   输出问题摘要，要求作者手动介入
3. 各 Agent 消费门禁产物时，以 `updated_at` 时间戳为准——只读取最新版本的
   门禁结果，不基于旧版本做判断

### 接口六：门禁产物与章节摘要的协作

章节摘要（`追踪/章节摘要.md`）写入时，应引用本章门禁的 `scores.overall` 分数：

```markdown
## 第37章：宗门大比
- 字数：2847
- 门禁：通过（综合 0.92）
- 关键实体：林晚晴、宗门大比、玄天剑诀
```

这使后续写前检索时，可以快速判断哪些章节质量较高，哪些章节有遗留问题。

## 十、门禁产物生命周期

```
创建：check_text.py --gate-report 首次创建 gate_ch{N}.json 和 check_ch{N}.json
    ↓
合并：rhythm_guard.py --gate-state 合并 rhythm 段
    ↓
合并：pacing-review（Agent）合并 pacing_review 段 + 创建 pacing_review_ch{N}.md
    ↓
合并：consistency-reviewer（Agent）合并 consistency 段 + 创建 consistency_ch{N}.md
    ↓
终态：passed=true → 进入下一章；passed=false → 修复后重跑门禁
    ↓
归档：书籍完结后，门禁产物保留在 追踪/门禁/ 目录中，作为全书质量追溯记录
```

**门禁产物永不删除**：即使修复后重跑门禁，旧版本的产物文件也应保留
（通过 `updated_at` 区分版本），或由脚本自动生成 `.bak` 备份。

---

## 十一、全管道产物清单

前文（一至十节）定义了「门禁产物」——即 `check_text.py` / `rhythm_guard.py` /
pacing-review / consistency-reviewer 四大子门禁的产物。本节将视野扩展到「全管道产物」：
每章写完后，从校对、质量评估、修复计划、文风校准、记忆更新、待办流转到发布就绪，
整条流水线应生成的完整产物列表。

全管道产物是门禁产物的**超集**：门禁产物（`gate_ch{N}.json`、`check_ch{N}.json`、
`pacing_review_ch{N}.md`、`consistency_ch{N}.md`）是全管道产物的一部分；本节新增
校对 / 质量 / 修复 / 校准 / 记忆 / 待办 / 发布七类产物，构成「写完即闭环」的完整证据链。

### 产物总览表

| 序号 | 逻辑名（文档称呼） | 落盘文件名 | 类别 | 产出方 | 生命周期 |
|---|---|---|---|---|---|
| 1 | `gate_result.json` | `gate_result_ch{N}.json` | 门禁综合 | check_text.py 首建 + 各子门禁合并 | 持久 |
| 2 | `consistency_report.md` | `consistency_report_ch{N}.md` | 一致性 | consistency-reviewer | 持久 |
| 3 | `copyedit_report.md` | `copyedit_report_ch{N}.md` | 校对 | copyeditor-agent | 持久 |
| 4 | `quality_report.md` | `quality_report_ch{N}.md` | 质量 | quality-reviewer | 持久 |
| 5 | `repair_plan.md` | `repair_plan_ch{N}.md` | 修复 | repair-planner | 临时 |
| 6 | `style_calibration.md` | `style_calibration_ch{N}.md` | 文风校准 | style-calibrator | 持久 |
| 7 | `memory_update.md` | `memory_update_ch{N}.md` | 记忆更新 | memory-keeper | 持久 |
| 8 | `pipeline_todo.md` | `pipeline_todo_ch{N}.md` | 待办流转 | pipeline-coordinator | 临时 |
| 9 | `publish_ready.md` | `publish_ready_ch{N}.md` | 发布就绪 | publish-gatekeeper | 持久 |
| 10 | `pacing_review.md` | `pacing_review_ch{N}.md` | 语义节奏 | pacing-reviewer | 持久 |

> **命名约定**：上层文档与跨 Agent 接口中以逻辑名（`gate_result.json`、
> `consistency_report.md` 等）指代；落盘时一律加 `_ch{N}` 后缀（章号不补零），
> 与第二节路径约定一致。
>
> **与既有产物的对应关系**：
> - `gate_result_ch{N}.json` 即第三节的 `gate_ch{N}.json`（同一文件，逻辑名为
>   `gate_result`）。本节为统一管道视图，采用 `gate_result_ch{N}.json` 这一更语义化的称呼；
>   既有脚本（`check_text.py --gate-state`、`rhythm_guard.py --gate-state`）仍读写
>   `gate_ch{N}.json`，二者是同一物理文件。
> - `consistency_report_ch{N}.md` 即第七节的 `consistency_ch{N}.md`。
> - `pacing_review_ch{N}.md` 即第六节的 `pacing_review_ch{N}.md`。
>
> 落盘时维持既有文件名不变，本节的逻辑名仅用于管道文档与 Agent 间对话。

### 产物生成顺序

每章写完后，产物按以下顺序生成（前置产物是后置产物的输入，禁止跳序）：

```
正文定稿
  │
  ├─① check_text.py --gate-report          → gate_result_ch{N}.json（首建）+ check_ch{N}.json
  ├─② rhythm_guard.py --gate-state          → 合并 rhythm 段到 gate_result_ch{N}.json
  ├─③ pacing-reviewer                       → pacing_review_ch{N}.md + 合并 pacing 段
  ├─④ consistency-reviewer                  → consistency_report_ch{N}.md + 合并 consistency 段
  ├─⑤ copyeditor-agent                      → copyedit_report_ch{N}.md
  ├─⑥ style-calibrator                      → style_calibration_ch{N}.md（条件触发）
  ├─⑦ quality-reviewer                      → quality_report_ch{N}.md（汇总①-⑥）
  ├─⑧ repair-planner（仅当⑦判定需修复时）    → repair_plan_ch{N}.md
  ├─⑨ memory-keeper                         → memory_update_ch{N}.md
  ├─⑩ pipeline-coordinator                  → pipeline_todo_ch{N}.md（汇总跨章待办）
  └─⑪ publish-gatekeeper                    → publish_ready_ch{N}.md（终态判定）
```

### 必需产物与可选产物

| 产物 | 必需/可选 | 触发条件 |
|---|---|---|
| `gate_result_ch{N}.json` | 必需 | 每章必出，管道唯一真相源，缺失则管道未执行 |
| `check_ch{N}.json` | 必需 | 每章必出，gate_result 的底层数据 |
| `consistency_report_ch{N}.md` | 必需（关键章）/ 可选（日常章） | 关键章定义见第九节接口四 |
| `pacing_review_ch{N}.md` | 必需（关键章）/ 可选（日常章） | 同上 |
| `copyedit_report_ch{N}.md` | 必需 | 每章必出，校对是基础质量门槛 |
| `quality_report_ch{N}.md` | 必需 | 每章必出，质量综合判定 |
| `repair_plan_ch{N}.md` | 条件必需 | 仅当 `quality_report.verdict != 通过` 时生成 |
| `style_calibration_ch{N}.md` | 可选 | 每 5 章例行一次，或文风漂移分数超阈值时触发 |
| `memory_update_ch{N}.md` | 必需 | 每章必出，驱动下一章写作的检索源 |
| `pipeline_todo_ch{N}.md` | 必需 | 每章必出，跨章待办的流转凭证 |
| `publish_ready_ch{N}.md` | 必需 | 每章必出，未出则视为未达发布标准 |

### 产物目录布局

全管道产物仍以 `追踪/门禁/` 为根，新增子目录区分门禁产物与扩展管道产物：

```
{书籍工程}/
└── 追踪/
    └── 门禁/
        ├── gate_ch{N}.json              # = gate_result_ch{N}.json（门禁综合，机器可读）
        ├── check_ch{N}.json             # 7 Gate 详情
        ├── rhythm_ch{N}.json            # 节奏配额（可选独立文件，默认并入 gate）
        ├── pacing_review_ch{N}.md       # = pacing_review.md
        ├── consistency_ch{N}.md         # = consistency_report.md
        ├── copyedit_report_ch{N}.md     # 新增：校对报告
        ├── quality_report_ch{N}.md      # 新增：质量报告
        ├── repair_plan_ch{N}.md         # 新增：修复计划（临时）
        ├── style_calibration_ch{N}.md   # 新增：文风校准
        ├── memory_update_ch{N}.md       # 新增：记忆更新
        ├── pipeline_todo_ch{N}.md       # 新增：待办流转（临时）
        └── publish_ready_ch{N}.md       # 新增：发布就绪
```

---

## 十二、各产物 Schema 定义

本节为十类产物逐一定义 schema。已在前文（三至七节）定义的产物（gate_result、
consistency、pacing）此处仅补充管道视图新增字段并引用前文；新增产物给出完整 schema。

### 12.1 gate_result_ch{N}.json（门禁综合状态）

完整 schema 见第三节。本节补充管道视图新增字段——在第三节 schema 基础上追加
`pipeline` 段：

```json
{
  "chapter": 37,
  "book": "仙道长青",
  "created_at": "2026-07-28T15:30:00",
  "updated_at": "2026-07-28T16:10:00",
  "passed": true,
  "fail_reason": null,
  "scores": { "overall": 0.92, "text_check": 0.95, "rhythm": 1.0, "pacing": 0.9, "consistency": 0.85 },
  "checks": { "text_check": {}, "rhythm": {}, "pacing_review": {}, "consistency": {} },
  "chapter_file": "正文/第037章_宗门大比.md",
  "chapter_mtime": "2026-07-28T15:20:00",
  "pipeline": {
    "copyedit_passed": true,
    "quality_verdict": "通过",
    "quality_score": 0.88,
    "repair_required": false,
    "style_calibrated": false,
    "memory_committed": true,
    "todo_count": 2,
    "publish_ready": true,
    "stages_completed": ["text_check","rhythm","pacing","consistency","copyedit","quality","memory","todo","publish"],
    "stages_pending": []
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `pipeline` | object | 是 | 管道视图段，汇总门禁之外各阶段状态 |
| `pipeline.copyedit_passed` | bool | 是 | 校对是否通过 |
| `pipeline.quality_verdict` | string | 是 | 质量判定：通过/有条件通过/需返工 |
| `pipeline.quality_score` | float | 是 | 质量综合分（0.0-1.0） |
| `pipeline.repair_required` | bool | 是 | 是否需要修复 |
| `pipeline.style_calibrated` | bool | 是 | 本章是否执行文风校准 |
| `pipeline.memory_committed` | bool | 是 | 记忆是否已提交到追踪文件 |
| `pipeline.todo_count` | int | 是 | 本章遗留待办数 |
| `pipeline.publish_ready` | bool | 是 | 是否达到发布标准 |
| `pipeline.stages_completed` | string[] | 是 | 已完成阶段列表 |
| `pipeline.stages_pending` | string[] | 是 | 待执行阶段列表（正常应为空） |

> `pipeline.publish_ready` 与独立的 `publish_ready_ch{N}.md` 的 `ready` 字段须保持一致；
> 任一更新时同步另一处。以 `publish_ready_ch{N}.md` 为权威（它是终态签收产物）。

### 12.2 consistency_report_ch{N}.md（一致性审查报告）

完整 schema 见第七节（`consistency_ch{N}.md`）。管道视图下补充一个 JSON 侧车文件
`consistency_ch{N}.meta.json`，供 quality-reviewer 机器读取：

```json
{
  "chapter": 37,
  "passed": true,
  "ooc_count": 0,
  "foreshadowing_issues": 0,
  "timeline_issues": 0,
  "entity_conflicts": 0,
  "cross_chapter_issues": 0,
  "score": 0.85,
  "reviewed_at": "2026-07-28T15:35:00"
}
```

| 字段 | 类型 | 必填 | 示例值 |
|---|---|---|---|
| `chapter` | int | 是 | `37` |
| `passed` | bool | 是 | `true` |
| `ooc_count` | int | 是 | `0` |
| `foreshadowing_issues` | int | 是 | `0` |
| `timeline_issues` | int | 是 | `0` |
| `entity_conflicts` | int | 是 | `0` |
| `cross_chapter_issues` | int | 是 | `0` |
| `score` | float | 是 | `0.85` |
| `reviewed_at` | string | 是 | `"2026-07-28T15:35:00"` |

### 12.3 copyedit_report_ch{N}.md（校对报告）

校对报告处理字面层问题：错别字、标点、格式、人名称谓、数字量词。与门禁的 7 Gate
（关注 AI 味与节奏）正交——校对管「对不对」，门禁管「像不像 AI 写的」。

#### Markdown 正文格式

```markdown
# 校对报告 — 第{N}章

## 一、错别字
- 行 {L}：「{原文}」→「{改正}」（原因：{同音/形近/手误}）

## 二、标点
- 行 {L}：{问题}（如：连续逗号、中英混用、引号不闭合）

## 三、格式
- 行 {L}：{问题}（如：段首缩进异常、全半角混排、空行缺失）

## 四、人名/称谓
- 行 {L}：「{称谓}」与人物卡不符（人物卡：{正确称谓}）

## 五、数字/量词
- 行 {L}：{问题}（如：数字大小写不一致、量词误用）

## 综合
- 校对结论：通过/需返工
- 修改项数：{N}
- 自动修正：{N}（可直接 apply）
- 需人工确认：{N}
```

#### 机器可读侧车 copyedit_ch{N}.meta.json

```json
{
  "chapter": 37,
  "passed": true,
  "fix_count": 6,
  "auto_fixable": 5,
  "need_confirm": 1,
  "by_category": {
    "typos": 2,
    "punctuation": 2,
    "format": 1,
    "naming": 1,
    "numbers": 0
  },
  "items": [
    {
      "line": 42,
      "category": "typos",
      "original": "按奈不住",
      "corrected": "按捺不住",
      "reason": "形近手误",
      "auto_fixable": true
    }
  ],
  "checked_at": "2026-07-28T15:40:00"
}
```

| 字段 | 类型 | 必填 | 示例值 | 说明 |
|---|---|---|---|---|
| `chapter` | int | 是 | `37` | 章号 |
| `passed` | bool | 是 | `true` | 校对是否通过（需人工确认项=0 且无 P0 错误） |
| `fix_count` | int | 是 | `6` | 修改项总数 |
| `auto_fixable` | int | 是 | `5` | 可自动 apply 的项数 |
| `need_confirm` | int | 是 | `1` | 需人工确认的项数 |
| `by_category` | object | 是 | `{...}` | 按类别统计 |
| `by_category.typos` | int | 是 | `2` | 错别字数 |
| `by_category.punctuation` | int | 是 | `2` | 标点问题数 |
| `by_category.format` | int | 是 | `1` | 格式问题数 |
| `by_category.naming` | int | 是 | `1` | 称谓问题数 |
| `by_category.numbers` | int | 是 | `0` | 数字量词问题数 |
| `items` | object[] | 是 | `[{...}]` | 逐条修改项 |
| `items[].line` | int | 是 | `42` | 行号 |
| `items[].category` | string | 是 | `"typos"` | 类别 |
| `items[].original` | string | 是 | `"按奈不住"` | 原文 |
| `items[].corrected` | string | 是 | `"按捺不住"` | 改正 |
| `items[].reason` | string | 是 | `"形近手误"` | 原因 |
| `items[].auto_fixable` | bool | 是 | `true` | 是否可自动修正 |
| `checked_at` | string | 是 | `"2026-07-28T15:40:00"` | 校对时间 |

### 12.4 quality_report_ch{N}.md（质量报告）

质量报告是管道的「总评」——汇总门禁、校对、一致性、文风校准的全部信号，给出本章
质量综合判定。它是 repair-planner 是否启动、publish-gatekeeper 是否放行的依据。

#### Markdown 正文格式

```markdown
# 质量报告 — 第{N}章

## 综合判定
- 结论：通过 / 有条件通过 / 需返工
- 综合分：{0.00-1.00}
- 是否需修复：是/否

## 维度评分
| 维度 | 分数 | 来源 | 说明 |
|---|---|---|---|
| 文笔 | 0.90 | gate.text_check + copyedit | 禁用词/毒句式/AI腔/校对 |
| 情节 | 0.85 | pacing + 人工 | 节奏/悬念/推进 |
| 人物 | 0.88 | consistency.ooc | OOC 检查 |
| 节奏 | 0.92 | rhythm + pacing | 配额+语义 |
| 一致性 | 0.85 | consistency | 伏笔/时间线/实体 |
| 沉浸感 | 0.80 | style_calibration + 人工 | 文风漂移/代入感 |

## 亮点
- {逐条列出本章做得好的地方}

## 短板
- {逐条列出本章的问题}

## 整改建议
- {若需返工，列出具体整改步骤}
```

#### 机器可读侧车 quality_ch{N}.meta.json

```json
{
  "chapter": 37,
  "overall_score": 0.88,
  "verdict": "通过",
  "need_repair": false,
  "dimensions": {
    "writing": 0.90,
    "plot": 0.85,
    "character": 0.88,
    "pacing": 0.92,
    "consistency": 0.85,
    "immersion": 0.80
  },
  "strengths": ["宗门大比的对抗节奏紧凑", "林晚晴的冷漠人设保持一致"],
  "weaknesses": ["第3幕信息密度略高", "章末悬念偏弱"],
  "sources": {
    "gate_score": 0.92,
    "copyedit_passed": true,
    "consistency_score": 0.85,
    "style_drift_score": 0.12
  },
  "reviewed_at": "2026-07-28T15:50:00"
}
```

| 字段 | 类型 | 必填 | 示例值 | 说明 |
|---|---|---|---|---|
| `chapter` | int | 是 | `37` | 章号 |
| `overall_score` | float | 是 | `0.88` | 综合分（六维加权） |
| `verdict` | string | 是 | `"通过"` | 判定：通过/有条件通过/需返工 |
| `need_repair` | bool | 是 | `false` | 是否需启动 repair-planner |
| `dimensions` | object | 是 | `{...}` | 六维评分 |
| `dimensions.writing` | float | 是 | `0.90` | 文笔维度 |
| `dimensions.plot` | float | 是 | `0.85` | 情节维度 |
| `dimensions.character` | float | 是 | `0.88` | 人物维度 |
| `dimensions.pacing` | float | 是 | `0.92` | 节奏维度 |
| `dimensions.consistency` | float | 是 | `0.85` | 一致性维度 |
| `dimensions.immersion` | float | 是 | `0.80` | 沉浸感维度 |
| `strengths` | string[] | 是 | `["..."]` | 亮点列表 |
| `weaknesses` | string[] | 是 | `["..."]` | 短板列表 |
| `sources` | object | 是 | `{...}` | 各源信号原始值 |
| `sources.gate_score` | float | 是 | `0.92` | 门禁综合分 |
| `sources.copyedit_passed` | bool | 是 | `true` | 校对是否通过 |
| `sources.consistency_score` | float | 是 | `0.85` | 一致性分 |
| `sources.style_drift_score` | float | 是 | `0.12` | 文风漂移分（越低越好） |
| `reviewed_at` | string | 是 | `"2026-07-28T15:50:00"` | 评审时间 |

> **verdict 判定规则**：
> - `通过`：overall_score ≥ 0.80 且无 P0 问题且 copyedit_passed=true
> - `有条件通过`：0.65 ≤ overall_score < 0.80，或存在 P1 问题
> - `需返工`：overall_score < 0.65，或存在 P0 问题，或 copyedit_passed=false

### 12.5 repair_plan_ch{N}.md（修复计划）

修复计划是**临时产物**——仅当 `quality_report.verdict != 通过` 时由 repair-planner
生成，指导修复动作；修复完成并重跑管道后，本文件标记为「已完成」并归档，不再作为
后续章节的输入。

#### Markdown 正文格式

```markdown
# 修复计划 — 第{N}章

## 触发来源
- 触发产物：quality_report_ch{N}.md / consistency_report_ch{N}.md / ...
- 触发问题：{一句话摘要}

## 待修复问题清单
| 序号 | 优先级 | 问题 | 来源 | 建议动作 |
|---|---|---|---|---|
| 1 | P0 | {问题描述} | {来源产物} | {修复动作} |

## 修复动作
1. {动作1：定位→改法→预期效果}
2. {动作2}

## 预估工作量
- 轻度/中度/重度

## 状态
- 当前状态：待执行 / 执行中 / 已完成 / 已放弃
- 过期时间：{ISO 8601}（修复完成后归档，不再消费）
```

#### 机器可读侧车 repair_plan_ch{N}.meta.json

```json
{
  "chapter": 37,
  "triggered_by": "quality_report_ch37.md",
  "trigger_summary": "第3幕信息密度过高，章末悬念偏弱",
  "issues": [
    {
      "id": "R1",
      "priority": "P1",
      "description": "第3幕在三段内塞入4个设定点，信息密度过高",
      "source": "quality_report_ch37.md",
      "action": "拆分设定点：保留2个本章呈现，另2个移至第38章对话中带出"
    }
  ],
  "actions": [
    "定位第3幕第18-24行，拆分设定点",
    "改写章末收束，强化悬念钩子"
  ],
  "estimated_effort": "中度",
  "status": "待执行",
  "created_at": "2026-07-28T15:55:00",
  "expires_at": "2026-07-28T17:00:00",
  "completed_at": null
}
```

| 字段 | 类型 | 必填 | 示例值 | 说明 |
|---|---|---|---|---|
| `chapter` | int | 是 | `37` | 章号 |
| `triggered_by` | string | 是 | `"quality_report_ch37.md"` | 触发来源产物 |
| `trigger_summary` | string | 是 | `"..."` | 触发问题摘要 |
| `issues` | object[] | 是 | `[{...}]` | 待修复问题 |
| `issues[].id` | string | 是 | `"R1"` | 问题编号 |
| `issues[].priority` | string | 是 | `"P1"` | 优先级：P0/P1/P2 |
| `issues[].description` | string | 是 | `"..."` | 问题描述 |
| `issues[].source` | string | 是 | `"quality_report_ch37.md"` | 来源产物 |
| `issues[].action` | string | 是 | `"..."` | 建议修复动作 |
| `actions` | string[] | 是 | `["..."]` | 修复动作步骤 |
| `estimated_effort` | string | 是 | `"中度"` | 预估工作量 |
| `status` | string | 是 | `"待执行"` | 状态：待执行/执行中/已完成/已放弃 |
| `created_at` | string | 是 | `"2026-07-28T15:55:00"` | 创建时间 |
| `expires_at` | string | 是 | `"2026-07-28T17:00:00"` | 过期时间（临时产物） |
| `completed_at` | string\|null | 是 | `null` | 完成时间，未完成为 null |

### 12.6 style_calibration_ch{N}.md（文风校准）

文风校准报告检测本章与全书基准文风的漂移。基准文风样本存于
`追踪/文风基准.md`（开书时由前 3 章沉淀）。

#### Markdown 正文格式

```markdown
# 文风校准 — 第{N}章

## 基准
- 基准样本：追踪/文风基准.md
- 基准章范围：第1-3章

## 漂移检测
| 维度 | 本章值 | 基准值 | 偏差 | 判定 |
|---|---|---|---|---|
| 平均段长 | 86字 | 92字 | -6.5% | 正常 |
| 平均句长 | 18字 | 16字 | +12.5% | 偏长 |
| 对话占比 | 28% | 35% | -7pt | 偏低 |
| 形容词密度 | 4.2/千字 | 3.5/千字 | +0.7 | 偏高 |
| 比喻密度 | 2.1/千字 | 1.8/千字 | +0.3 | 正常 |

## 漂移分数
- 综合漂移：0.12（轻度，<0.15 为正常）

## 校准建议
- {逐条列出需回调的维度及改法}
```

#### 机器可读侧车 style_calibration_ch{N}.meta.json

```json
{
  "chapter": 37,
  "baseline_ref": "追踪/文风基准.md",
  "baseline_range": [1, 3],
  "metrics": {
    "avg_paragraph_len": 86,
    "avg_sentence_len": 18,
    "dialogue_ratio": 0.28,
    "adj_density": 4.2,
    "metaphor_density": 2.1
  },
  "baseline_metrics": {
    "avg_paragraph_len": 92,
    "avg_sentence_len": 16,
    "dialogue_ratio": 0.35,
    "adj_density": 3.5,
    "metaphor_density": 1.8
  },
  "drift_score": 0.12,
  "drift_dimensions": ["avg_sentence_len", "dialogue_ratio", "adj_density"],
  "suggestions": ["拆分过长句子", "增加对话段比例", "削减堆砌形容词"],
  "calibrated_at": "2026-07-28T16:00:00"
}
```

| 字段 | 类型 | 必填 | 示例值 | 说明 |
|---|---|---|---|---|
| `chapter` | int | 是 | `37` | 章号 |
| `baseline_ref` | string | 是 | `"追踪/文风基准.md"` | 基准样本路径 |
| `baseline_range` | int[] | 是 | `[1, 3]` | 基准章范围 |
| `metrics` | object | 是 | `{...}` | 本章指标 |
| `baseline_metrics` | object | 是 | `{...}` | 基准指标 |
| `drift_score` | float | 是 | `0.12` | 漂移分数（0-1，越低越好，<0.15 正常） |
| `drift_dimensions` | string[] | 是 | `["..."]` | 漂移维度列表 |
| `suggestions` | string[] | 是 | `["..."]` | 校准建议 |
| `calibrated_at` | string | 是 | `"2026-07-28T16:00:00"` | 校准时间 |

> `metrics` 与 `baseline_metrics` 的键须一一对应，键名同 `--style-stats` 输出。

### 12.7 memory_update_ch{N}.md（记忆更新）

记忆更新报告是管道与「追踪系统」的桥梁——本章发生的角色状态变更、伏笔埋设/兑现、
时间线事件、实体增删、关系变动，经 memory-keeper 整理后写入对应追踪文件
（人物卡、伏笔台账、时间线、实体索引、关系网）。它是下一章写作前检索的源。

#### Markdown 正文格式

```markdown
# 记忆更新 — 第{N}章

## 一、角色状态变更
- {角色名}：{变更前} → {变更后}（依据：本章第{L}行）

## 二、伏笔
- 埋设：{伏笔描述}（ID：F{N}，预计兑现章：第{M}章）
- 兑现：{伏笔描述}（ID：F{K}，埋设于第{P}章）

## 三、时间线
- {事件}（时间点：{小说内时间}）

## 四、实体
- 新增：{实体名}（类型：{物品/地点/组织/功法}）
- 变更：{实体名} {字段}：{旧值} → {新值}

## 五、关系
- {角色A} ↔ {角色B}：{旧关系} → {新关系}

## 六、世界观设定补充
- {新设定点}

## 待写入文件
- 追踪/人物卡/{角色}.md
- 追踪/伏笔台账.md
- 追踪/时间线.md
- 追踪/实体索引.md
```

#### 机器可读侧车 memory_update_ch{N}.meta.json

```json
{
  "chapter": 37,
  "character_state_updates": [
    {
      "character": "林晚晴",
      "field": "修为",
      "before": "筑基中期",
      "after": "筑基后期",
      "evidence_line": 156
    }
  ],
  "foreshadowing_updates": [
    {
      "type": "plant",
      "id": "F37",
      "description": "玄天剑诀残页第三页的出现",
      "planted_at": 37,
      "expected_payoff": 45
    }
  ],
  "timeline_events": [
    {
      "event": "宗门大比当日",
      "fiction_time": "建元四十七年三月初九"
    }
  ],
  "entity_updates": [
    {
      "type": "add",
      "name": "玄天剑诀残页",
      "entity_type": "物品"
    }
  ],
  "relationship_updates": [
    {
      "from": "林晚晴",
      "to": "陈墨",
      "before": "同门",
      "after": "竞争对手"
    }
  ],
  "world_setting_updates": [],
  "target_files": [
    "追踪/人物卡/林晚晴.md",
    "追踪/伏笔台账.md",
    "追踪/时间线.md",
    "追踪/实体索引.md"
  ],
  "committed": true,
  "updated_at": "2026-07-28T16:05:00"
}
```

| 字段 | 类型 | 必填 | 示例值 | 说明 |
|---|---|---|---|---|
| `chapter` | int | 是 | `37` | 章号 |
| `character_state_updates` | object[] | 是 | `[{...}]` | 角色状态变更 |
| `character_state_updates[].character` | string | 是 | `"林晚晴"` | 角色名 |
| `character_state_updates[].field` | string | 是 | `"修为"` | 变更字段 |
| `character_state_updates[].before` | string | 是 | `"筑基中期"` | 变更前 |
| `character_state_updates[].after` | string | 是 | `"筑基后期"` | 变更后 |
| `character_state_updates[].evidence_line` | int | 是 | `156` | 依据行号 |
| `foreshadowing_updates` | object[] | 是 | `[{...}]` | 伏笔更新 |
| `foreshadowing_updates[].type` | string | 是 | `"plant"` | 类型：plant/payoff |
| `foreshadowing_updates[].id` | string | 是 | `"F37"` | 伏笔ID |
| `foreshadowing_updates[].description` | string | 是 | `"..."` | 描述 |
| `foreshadowing_updates[].planted_at` | int | 是 | `37` | 埋设章 |
| `foreshadowing_updates[].expected_payoff` | int | 可选 | `45` | 预计兑现章（plant 时填） |
| `timeline_events` | object[] | 是 | `[{...}]` | 时间线事件 |
| `timeline_events[].event` | string | 是 | `"宗门大比当日"` | 事件 |
| `timeline_events[].fiction_time` | string | 是 | `"建元四十七年三月初九"` | 小说内时间 |
| `entity_updates` | object[] | 是 | `[{...}]` | 实体更新 |
| `entity_updates[].type` | string | 是 | `"add"` | 类型：add/modify/remove |
| `entity_updates[].name` | string | 是 | `"玄天剑诀残页"` | 实体名 |
| `entity_updates[].entity_type` | string | 是 | `"物品"` | 实体类型 |
| `relationship_updates` | object[] | 是 | `[{...}]` | 关系更新 |
| `relationship_updates[].from` | string | 是 | `"林晚晴"` | 角色A |
| `relationship_updates[].to` | string | 是 | `"陈墨"` | 角色B |
| `relationship_updates[].before` | string | 是 | `"同门"` | 旧关系 |
| `relationship_updates[].after` | string | 是 | `"竞争对手"` | 新关系 |
| `world_setting_updates` | string[] | 是 | `[]` | 世界观设定补充 |
| `target_files` | string[] | 是 | `["..."]` | 待写入追踪文件 |
| `committed` | bool | 是 | `true` | 是否已提交写入 |
| `updated_at` | string | 是 | `"2026-07-28T16:05:00"` | 更新时间 |

### 12.8 pipeline_todo_ch{N}.md（待办流转）

待办流转是**临时产物**——汇总本章遗留的、需在后续章节处理的事项（如伏笔待兑现、
角色弧待推进、设定待展开、节奏待回调）。修复完成后或被后续章节消费后，本文件归档。

#### Markdown 正文格式

```markdown
# 管道待办 — 第{N}章

## 本章遗留待办
- [ ] {待办1}（责任：{Agent}，目标章：第{M}章）
- [ ] {待办2}

## 延后项
- {已识别但本章不处理的事项，及延后理由}

## 跨章标记
- {需在后续章节注意的连续性标记}

## 已结清
- [x] {来自前章待办、本章已处理的事项}（来源：pipeline_todo_ch{K}.md）
```

#### 机器可读侧车 pipeline_todo_ch{N}.meta.json

```json
{
  "chapter": 37,
  "todos": [
    {
      "id": "T37-1",
      "description": "兑现F37伏笔：玄天剑诀残页的来历",
      "owner": "写作特工",
      "target_chapter": 45,
      "status": "open"
    }
  ],
  "deferred_items": [
    {
      "description": "陈墨身世线暂不展开",
      "reason": "与当前宗门大比线冲突，延至第50章后"
    }
  ],
  "cross_chapter_flags": ["林晚晴修为突破后性格可能松动，注意第38章人设连贯"],
  "settled_items": [
    {
      "id": "T35-2",
      "description": "交代宗门大比规则",
      "settled_at": 37
    }
  ],
  "owner": "pipeline-coordinator",
  "created_at": "2026-07-28T16:08:00",
  "expires_at": "2026-07-28T18:00:00"
}
```

| 字段 | 类型 | 必填 | 示例值 | 说明 |
|---|---|---|---|---|
| `chapter` | int | 是 | `37` | 章号 |
| `todos` | object[] | 是 | `[{...}]` | 待办项 |
| `todos[].id` | string | 是 | `"T37-1"` | 待办ID |
| `todos[].description` | string | 是 | `"..."` | 描述 |
| `todos[].owner` | string | 是 | `"写作特工"` | 责任Agent |
| `todos[].target_chapter` | int | 是 | `45` | 目标章 |
| `todos[].status` | string | 是 | `"open"` | 状态：open/done/cancelled |
| `deferred_items` | object[] | 是 | `[{...}]` | 延后项 |
| `deferred_items[].description` | string | 是 | `"..."` | 描述 |
| `deferred_items[].reason` | string | 是 | `"..."` | 延后理由 |
| `cross_chapter_flags` | string[] | 是 | `["..."]` | 跨章标记 |
| `settled_items` | object[] | 是 | `[{...}]` | 已结清项 |
| `settled_items[].id` | string | 是 | `"T35-2"` | 原待办ID |
| `settled_items[].description` | string | 是 | `"..."` | 描述 |
| `settled_items[].settled_at` | int | 是 | `37` | 结清章 |
| `owner` | string | 是 | `"pipeline-coordinator"` | 产出方 |
| `created_at` | string | 是 | `"2026-07-28T16:08:00"` | 创建时间 |
| `expires_at` | string | 是 | `"2026-07-28T18:00:00"` | 过期时间（临时产物） |

### 12.9 publish_ready_ch{N}.md（发布就绪）

发布就绪是管道的**终态签收**——确认所有前置产物齐备且通过，本章可进入发布流程。
未生成本文件或 `ready=false` 的章节，禁止发布、禁止作为下一章的前置。

#### Markdown 正文格式

```markdown
# 发布就绪签收 — 第{N}章

## 终态判定
- 是否就绪：是/否
- 签收时间：{ISO 8601}
- 发布版本：v{N}.0

## 前置产物检查
| 产物 | 存在 | 状态 |
|---|---|---|
| gate_result_ch{N}.json | 是 | passed=true |
| consistency_report_ch{N}.md | 是 | passed=true |
| copyedit_report_ch{N}.md | 是 | passed=true |
| quality_report_ch{N}.md | 是 | verdict=通过 |
| memory_update_ch{N}.md | 是 | committed=true |
| pipeline_todo_ch{N}.md | 是 | 无 P0 未结清 |

## 终检项
- [x] 字数在区间内
- [x] 无 P0 阻断问题
- [x] 记忆已提交
- [x] 待办无 P0 遗留
- [ ] {若有阻断项，列于此}

## 阻断项
- {若无，写「无」}
```

#### 机器可读侧车 publish_ready_ch{N}.meta.json

```json
{
  "chapter": 37,
  "ready": true,
  "signed_off_at": "2026-07-28T16:10:00",
  "publish_version": "v37.0",
  "prerequisites": {
    "gate_result": { "exists": true, "passed": true },
    "consistency_report": { "exists": true, "passed": true },
    "copyedit_report": { "exists": true, "passed": true },
    "quality_report": { "exists": true, "verdict": "通过" },
    "memory_update": { "exists": true, "committed": true },
    "pipeline_todo": { "exists": true, "p0_open": 0 }
  },
  "final_checks": {
    "word_count_ok": true,
    "no_p0_blocker": true,
    "memory_committed": true,
    "no_p0_todo": true
  },
  "blockers": []
}
```

| 字段 | 类型 | 必填 | 示例值 | 说明 |
|---|---|---|---|---|
| `chapter` | int | 是 | `37` | 章号 |
| `ready` | bool | 是 | `true` | 是否发布就绪 |
| `signed_off_at` | string | 是 | `"2026-07-28T16:10:00"` | 签收时间 |
| `publish_version` | string | 是 | `"v37.0"` | 发布版本号 |
| `prerequisites` | object | 是 | `{...}` | 前置产物检查 |
| `prerequisites.gate_result` | object | 是 | `{...}` | 门禁综合检查 |
| `prerequisites.gate_result.exists` | bool | 是 | `true` | 是否存在 |
| `prerequisites.gate_result.passed` | bool | 是 | `true` | 是否通过 |
| `prerequisites.consistency_report` | object | 是 | `{...}` | 一致性检查 |
| `prerequisites.copyedit_report` | object | 是 | `{...}` | 校对检查 |
| `prerequisites.quality_report` | object | 是 | `{...}` | 质量检查 |
| `prerequisites.quality_report.verdict` | string | 是 | `"通过"` | 质量判定 |
| `prerequisites.memory_update` | object | 是 | `{...}` | 记忆更新检查 |
| `prerequisites.memory_update.committed` | bool | 是 | `true` | 是否已提交 |
| `prerequisites.pipeline_todo` | object | 是 | `{...}` | 待办检查 |
| `prerequisites.pipeline_todo.p0_open` | int | 是 | `0` | P0 未结清数 |
| `final_checks` | object | 是 | `{...}` | 终检项 |
| `final_checks.word_count_ok` | bool | 是 | `true` | 字数是否达标 |
| `final_checks.no_p0_blocker` | bool | 是 | `true` | 是否无 P0 阻断 |
| `final_checks.memory_committed` | bool | 是 | `true` | 记忆是否提交 |
| `final_checks.no_p0_todo` | bool | 是 | `true` | 是否无 P0 待办 |
| `blockers` | string[] | 是 | `[]` | 阻断项列表（无则空数组） |

> **ready 判定规则**：`ready = prerequisites 全 true ∧ final_checks 全 true ∧ blockers 为空`。
> 任一为假则 `ready=false`，并在 `blockers` 列出原因。

### 12.10 pacing_review_ch{N}.md（语义节奏审查报告）

完整 schema 见第六节。管道视图下补充 JSON 侧车 `pacing_ch{N}.meta.json`：

```json
{
  "chapter": 37,
  "passed": true,
  "conclusion": "通过",
  "gear_consistency": "一致",
  "quota_violation": false,
  "quota_fraud": false,
  "suspense_grade": "强",
  "hidden_acceleration": false,
  "score": 0.9,
  "reviewed_at": "2026-07-28T15:33:00"
}
```

| 字段 | 类型 | 必填 | 示例值 | 说明 |
|---|---|---|---|---|
| `chapter` | int | 是 | `37` | 章号 |
| `passed` | bool | 是 | `true` | 是否通过 |
| `conclusion` | string | 是 | `"通过"` | 结论 |
| `gear_consistency` | string | 是 | `"一致"` | 档位一致性 |
| `quota_violation` | bool | 是 | `false` | 是否配额越界 |
| `quota_fraud` | bool | 是 | `false` | 是否配额欺诈 |
| `suspense_grade` | string | 是 | `"强"` | 章末悬念等级 |
| `hidden_acceleration` | bool | 是 | `false` | 是否隐性加速 |
| `score` | float | 是 | `0.9` | 节奏分（0-1） |
| `reviewed_at` | string | 是 | `"2026-07-28T15:33:00"` | 审查时间 |

---

## 十三、跨 Agent 消费接口（全管道扩展）

第九节定义了门禁产物的六条消费接口。本节扩展到全管道产物，明确四个核心 Agent
各自消费哪些产物、产出哪些产物、消费顺序与约束。

### Agent 角色与产物流向总览

```
                    ┌──────────────┐
                    │  策划主编     │  读：quality/memory/todo/consistency
                    │ (planner)    │  写：repair_plan/style_calibration 建议
                    └──────┬───────┘
                           │ 指导
                           ▼
                    ┌──────────────┐
   memory_update ◀──│  写作特工     │──▶ 正文（输入给全管道）
   pipeline_todo ◀──│ (writer)     │
                    └──────┬───────┘
                           │ 正文
                           ▼
                    ┌──────────────┐
                    │  反AI编辑     │  读：gate_result/copyedit/style_calibration
                    │ (anti-ai)    │  写：copyedit_report（部分）/ 改后正文
                    └──────┬───────┘
                           │ 改后正文
                           ▼
                    ┌──────────────┐
                    │  核实官       │  读：全部产物（终态校验）
                    │ (verifier)   │  写：quality_report/publish_ready
                    └──────────────┘
```

### 13.1 策划主编（planner / 主编 Agent）消费接口

**职责**：全书规划、章纲把控、跨章一致性调度、修复与校准决策。

**读取产物**：

| 产物 | 用途 | 读取时机 |
|---|---|---|
| `quality_report_ch{N}.md` | 判断本章质量是否达标，决定是否启动修复 | 每章管道完成后 |
| `memory_update_ch{N}.md` | 掌握角色/伏笔/时间线进展，调整后续章纲 | 每章管道完成后 |
| `pipeline_todo_ch{N}.md` | 接收跨章待办，分配到后续章纲 | 每章管道完成后 |
| `consistency_report_ch{N}.md` | 评估一致性风险，决定是否调整设定 | 关键章后 |
| `pacing_review_ch{N}.md` | 评估节奏走势，调整后续节奏配额 | 关键章后 |
| `style_calibration_ch{N}.md` | 评估文风漂移，决定是否回调 | 每 5 章或漂移时 |
| `gate_result_ch{N}.json`（pipeline 段） | 全局管道进度监控 | 每章管道完成后 |

**写入产物**：

| 产物 | 用途 |
|---|---|
| `repair_plan_ch{N}.md`（策划主编可发起） | 当判定需返工时，下达修复计划 |
| `style_calibration` 建议 | 向 style-calibrator 提供校准方向 |
| 后续章纲调整 | 基于 memory/todo 调整 `追踪/章纲/` |

**消费约束**：
- 策划主编**只读**门禁详细产物（`check_ch{N}.json`），不直接修改正文。
- 策划主编发起的 `repair_plan` 须指明优先级与目标章，不可含糊。
- 策划主编消费 `pipeline_todo` 时，须将 open 项分配到具体目标章纲，不可悬空。

### 13.2 写作特工（writer Agent）消费接口

**职责**：执笔写正文，是产物的「源头」。

**读取产物**（写前检索）：

| 产物 | 用途 | 读取时机 |
|---|---|---|
| `memory_update_ch{N-1}.md` | 获取上一章的角色状态/伏笔/时间线，保证连贯 | 写第 N 章前 |
| `pipeline_todo_ch{N-1}.md` | 获取需在本章结清的待办 | 写第 N 章前 |
| `gate_result_ch{N-1}.json` | 确认上一章已通过门禁（前置约束） | 写第 N 章前 |
| `style_calibration_ch{N-1}.md`（若有） | 校准本章文风，避免延续漂移 | 写第 N 章前 |
| `consistency_report_ch{N-1}.md`（关键章） | 规避上一章暴露的一致性风险 | 写第 N 章前 |
| `追踪/文风基准.md` | 对齐基准文风 | 写第 N 章前 |

**写入产物**：
- 正文文件（`正文/第XXX章_标题.md`）——管道的全部输入。
- 写作特工**不直接写**任何 `_ch{N}.md` 报告产物（那些由专职 Agent 产出）。

**消费约束**：
- 写作特工写第 N 章前，**必须**确认 `gate_result_ch{N-1}.passed == true`，否则禁止开写。
- 写作特工须在本章正文中**显式回应** `pipeline_todo_ch{N-1}` 中 target_chapter==N 的 open 项；
  回应情况由 memory-keeper 在 `memory_update_ch{N}` 的 `settled_items` 中体现。
- 写作特工消费 `style_calibration` 时，须在章末自检段说明本章文风校准动作。

### 13.3 反AI编辑（anti-ai / 去AI味 Agent）消费接口

**职责**：去 AI 味、校对润色、文风校准执行。详见 `deslop-engineering.md`。

**读取产物**：

| 产物 | 用途 | 读取时机 |
|---|---|---|
| `gate_result_ch{N}.json`（text_check 段） | 获取 AI 味分数、分级、命中数，确定润色遍数 | 门禁通过后 |
| `check_ch{N}.json` | 获取 7 Gate 详细命中，定位待改位置 | 门禁通过后 |
| `copyedit_report_ch{N}.md` | 获取字面层问题，与去 AI 味同步处理 | 校对完成后 |
| `style_calibration_ch{N}.md` | 获取文风漂移维度，去 AI 味时一并回调 | 校准完成后 |
| `追踪/禁用词.txt` + `.deslop-whitelist` | 去AI味的词表依据 | 每次润色 |
| `deslop-engineering.md` | 工作流依据（三遍法/两遍式/收敛终止） | 每次润色 |

**写入产物**：
- 改后正文（直接覆盖正文文件，或产出 diff 供核实官复核）。
- `copyedit_report_ch{N}.md`（当反AI编辑兼任校对时）。
- 去AI味自查报告（可选，对应既有 `anti_ai_ch{N}.md`）。

**消费约束**：
- 反AI编辑须遵循 `deslop-engineering.md` 的删除比例上限与 `[需复核]` 机制，不得超限。
- 反AI编辑改后须重跑 `check_text.py` 验证 blocking 清零，更新 `gate_result` 的
  `text_check` 段与 `deslop_score`。
- 反AI编辑不得删除伏笔/因果锚点（依据 `memory_update` 与伏笔台账交叉校验）。

### 13.4 核实官（verifier / 质量与发布签收 Agent）消费接口

**职责**：终态校验——汇总全部产物，判定质量与发布就绪。是管道的「守门人」。

**读取产物**（核实官读取**全部**管道产物）：

| 产物 | 用途 |
|---|---|
| `gate_result_ch{N}.json`（全量） | 门禁综合状态与管道进度 |
| `check_ch{N}.json` | 7 Gate 详情，复核 blocking 是否清零 |
| `consistency_report_ch{N}.md` + meta | 一致性终态 |
| `pacing_review_ch{N}.md` + meta | 节奏终态 |
| `copyedit_report_ch{N}.md` + meta | 校对终态 |
| `quality_report_ch{N}.md`（若由他方先出，核实官复核） | 质量终态 |
| `repair_plan_ch{N}.md`（若存在） | 修复是否已完成 |
| `style_calibration_ch{N}.md` + meta | 文风终态 |
| `memory_update_ch{N}.md` + meta | 记忆是否已提交 |
| `pipeline_todo_ch{N}.md` + meta | 待办是否有 P0 遗留 |

**写入产物**：

| 产物 | 用途 |
|---|---|
| `quality_report_ch{N}.md` + meta | 质量综合判定（若不由专职 quality-reviewer 出，则由核实官出） |
| `publish_ready_ch{N}.md` + meta | 发布就绪签收（核实官是唯一签收方） |

**消费约束**：
- 核实官是 `publish_ready_ch{N}.md` 的**唯一写入方**，其他 Agent 不得签收发布。
- 核实官签收前须校验全部前置产物 `exists` 且状态通过，任一缺失或不通过 → `ready=false`。
- 核实官发现质量报告与底层产物矛盾时（如 quality 说通过但 copyedit 未通过），以底层
  产物为准，判 `ready=false` 并在 `blockers` 记录矛盾。

### 13.5 消费接口通用约束

1. **版本一致性**：所有 Agent 消费产物时以 `updated_at` / `signed_off_at` 为准，只读最新版本。
2. **不可跨阶段消费**：写作特工不得在门禁未通过时消费 `quality_report`（此时它尚未生成）。
3. **产物缺失即阻断**：任何 Agent 发现其应消费的产物缺失，须停止并报错，不得用旧章产物替代。
4. **写后改动失效**：若正文 `chapter_mtime` 与 `gate_result.chapter_mtime` 不一致，所有
   下游产物（copyedit 之后）视为失效，须重跑管道。

---

## 十四、产物生命周期分类

产物分两类生命周期：**持久产物**（跨章/跨会话保留，用于追踪与回溯）与
**临时产物**（写完即弃/消费后归档，不进入长期记忆）。

### 14.1 生命周期分类表

| 产物 | 生命周期 | 保留策略 | 理由 |
|---|---|---|---|
| `gate_result_ch{N}.json` | 持久 | 永久保留，跨会话可读 | 门禁真相源，跨会话查验依赖 |
| `check_ch{N}.json` | 持久 | 永久保留 | 7 Gate 详情，回溯与审计依赖 |
| `consistency_report_ch{N}.md` | 持久 | 永久保留 | 一致性问题跨章追踪 |
| `pacing_review_ch{N}.md` | 持久 | 永久保留 | 节奏走势分析依赖历史 |
| `copyedit_report_ch{N}.md` | 持久 | 永久保留 | 校对记录可回溯错别字模式 |
| `quality_report_ch{N}.md` | 持久 | 永久保留 | 质量趋势分析依赖 |
| `style_calibration_ch{N}.md` | 持久 | 永久保留 | 文风漂移历史，基准更新依据 |
| `memory_update_ch{N}.md` | 持久 | 永久保留 | 角色弧/伏笔/时间线的变更证据链 |
| `publish_ready_ch{N}.md` | 持久 | 永久保留 | 发布签收凭证，版本追溯 |
| `repair_plan_ch{N}.md` | **临时** | 修复完成后归档，不作为后续章输入 | 一次性指令，修复完即失效 |
| `pipeline_todo_ch{N}.md` | **临时** | 待办被结清后归档，结清项迁移到 memory | 流转凭证，结清后失去意义 |

### 14.2 持久产物管理规则

1. **永不删除**：持久产物即使重跑管道也保留旧版本（`.bak` 备份或 `updated_at` 区分）。
2. **跨会话可读**：`resume.py` 启动时优先读取最新章的持久产物，恢复管道状态。
3. **归档位置**：书籍完结后，持久产物留在 `追踪/门禁/` 作为全书质量追溯记录，
   不迁移、不压缩。
4. **索引生成**：`追踪/门禁/` 下的持久产物可由脚本生成 `pipeline_index.md`——
   按章号列出各产物是否存在、是否通过，供快速检索。

### 14.3 临时产物管理规则

1. **明确过期时间**：临时产物 meta 中 `expires_at` 必填，超过该时间视为过期。
2. **消费后归档**：
   - `repair_plan_ch{N}.md`：修复完成并重跑管道、`quality_report.verdict == 通过` 后，
     `status` 改为「已完成」，文件移至 `追踪/门禁/归档/` 子目录。
   - `pipeline_todo_ch{N}.md`：open 项全部结清后，`settled_items` 迁移到对应
     `memory_update`，本文件移至 `追踪/门禁/归档/`。
3. **不进入长期记忆**：临时产物的内容不得被 memory-keeper 写入人物卡/伏笔台账等
   持久追踪文件——只有 `memory_update` 是记忆写入的合法来源。
4. **跨会话清理**：新会话启动时，`resume.py` 检查临时产物是否过期，过期的提示归档。

### 14.4 生命周期与管道阶段的关系

```
正文定稿
  │
  ├─①②③④ 门禁阶段 ──→ 产出持久产物（gate_result/check/consistency/pacing）
  ├─⑤⑥   校对/校准 ──→ 产出持久产物（copyedit/style_calibration）
  ├─⑦     质量判定 ──→ 产出持久产物（quality_report）
  ├─⑧     修复阶段 ──→ 产出临时产物（repair_plan）──→ 修复后归档
  ├─⑨     记忆提交 ──→ 产出持久产物（memory_update）──→ 写入追踪文件
  ├─⑩     待办流转 ──→ 产出临时产物（pipeline_todo）──→ 结清后归档
  └─⑪     发布签收 ──→ 产出持久产物（publish_ready）──→ 终态
```

**关键原则**：临时产物（repair_plan、pipeline_todo）是「过程凭证」，服务于当章的修复
与流转；持久产物是「状态证据」，服务于全书的追踪与回溯。两者不可混淆——把临时产物
当持久保留会造成噪音，把持久产物当临时清理会丢失证据链。

### 14.5 产物完整性校验（扩展）

第九节接口四定义了门禁产物的完整性校验。全管道视图下，`validate_tracking.py` 应扩展
校验范围：

**持久产物必需性校验**（每章）：
- `gate_result_ch{N}.json` 必须存在
- `check_ch{N}.json` 必须存在
- `copyedit_report_ch{N}.md` 必须存在
- `quality_report_ch{N}.md` 必须存在
- `memory_update_ch{N}.md` 必须存在
- `publish_ready_ch{N}.md` 必须存在

**条件必需校验**：
- 关键章：`consistency_report_ch{N}.md`、`pacing_review_ch{N}.md` 必须存在
- `quality_report.verdict != 通过`：`repair_plan_ch{N}.md` 必须存在（临时，归档前校验）

**一致性校验**：
- `publish_ready_ch{N}.ready == true` 时，所有持久前置产物必须 `passed/committed == true`
- `gate_result.pipeline.stages_pending` 必须为空数组（管道须闭环）

校验失败时，`validate_tracking.py` 输出缺失产物清单与受影响章号，阻断下一章写作。