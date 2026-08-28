# 日更写前 fail-fast

用于 `daily-batch.md` 或托管连写中每一章的写前检查。它只判断当前章事务能否安全开始；
不把对标、RAG、图谱或联网能力变成所有章节的固定门槛。

## 插入位置与分工

在 `chapter-loop.md` Step 1 读章纲之后、Step 2 装配上下文之前执行。

| 文件 | 职责 | 粒度 |
|---|---|---|
| `chapter-loop.md` | 单章章意图、场景渲染、stage 门禁与 journal 提交/恢复 | 每章 |
| `daily-batch.md` | 2–3 章的串行编排与批次退化防护 | 每批 |
| `daily-failfast.md` | 当前章 required context 完备性与 conditional fallback | 每章写前 |

上一章未完成事务时先输出 `transaction_incomplete` 并恢复；不得先写完多章再统一过门禁或补追踪。

```bash
python scripts/resume.py "{book}"
python scripts/chapter_transaction.py status "{book}"
```

status 不是完成证明；看到 prepared/validated/committing/recovering 或 corrupt 都不得开下一章。
需要放弃未完成事务时用 `python scripts/chapter_transaction.py recover "{book}"`；有外部冲突则
保留副本并交作者处理，不强制覆盖。无欠账后按 `chapter-loop.md` prepare 创建 stage/checkpoint。

## 权威顺序

作者本轮明确决定 > 已发生正文 > 最新追踪状态 > 锁定大纲 > 设定 > 题材卡 > 对标材料 >
通用建议。低权威来源冲突时不得阻断高权威事实，也不得静默覆盖；记录冲突和采用的来源。

## Required context

下面四项缺失会使正文不安全，必须 fail-fast：

1. **当前章纲**：含目标、授权 beats、状态变化、禁放信息或可推导的等价内容。
2. **前章承接**：上一章正文或可靠摘要，足以知道当前场景、未兑现钩子和最近结算。
3. **出场人物最新状态**：至少包括位置、关系、持有物、伤势/能力和近期选择中与本章相关的项。
4. **相关未结约束**：本章触及的伏笔、时间线、世界硬规则；若确认没有，显式记“none”。

检查输出：

```text
[OK]   current_outline: 大纲/章纲_第XXX章.md
[OK]   previous_context: 正文/第XXX章.md 或 追踪/章节摘要.md#第XXX章
[OK]   appearing_character_state: 追踪/角色状态.md
[OK]   unresolved_constraints: 追踪/伏笔台账.md + 追踪/时间线.md
```

缺项时立即停止：

```text
required_context_missing
path: {缺失路径或字段}
impact: {缺失会导致的具体连续性风险}
remediation: {补纲、补账、回读正文或向作者确认的可执行动作}
checkpoint: {最后有效章事务}
```

不得用“凭印象”“大概如此”脑补后放行。

## Chapter intent budget gate

Required context 齐全后，按 `references/craft/scene-rendering.md` 形成章意图。逐 beat 判断能否形成包含
目的、阻力、行动/反应和可观察变化的 scene unit。

授权事件不足以支撑目标篇幅时：

```text
outline_underfilled
missing_beat_budget: 还缺 {N} 个可产生状态变化的 beat，或将目标从 {target} 字调整为约 {supported} 字
remediation: {列出需要作者补充的具体冲突、选择、代价或状态变化空位}
```

到此停止。禁止用解释、同义重复、内心独白、环境描写、无目的对话或未授权反转填充。

## Conditional context

只在章意图确实需要时检查；缺失时记录 fallback，通常不阻断无关章节。

| 来源/能力 | 何时需要 | 不可用时的明确 fallback |
|---|---|---|
| 主题材卡 | 爽点、禁用词或场景规范依赖题材差异 | 按 `references/genres/INDEX.md` 匹配；无卡则用通用工艺并标注 |
| 作者文风/文风锚 | 用户要求定向声线或项目已有稳定文风 | 以用户本轮文风指示为准；无指示则保留当前正文可观察声线 |
| 对标情绪/节奏/章节 | 用户明确要求对标，或章意图引用该来源 | 标记 benchmark unavailable，按本书大纲与文风继续，不伪造对标结论 |
| 敏感词替换表 | 涉及真实地名、机构、人物或事件 | 向作者确认代称或创建待确认条目，不现场冒充已登记规则 |
| RAG/知识图谱 | 摘要不足以定位旧细节 | 用实体索引、摘要关键词和正文搜索回退，记录搜索范围 |
| 联网研究 | 结论具有时效性或用户要求核验 | 标为未联网核验，仅使用本地资料；若准确性是硬前提则 `tool_unavailable` 停止 |

状态格式：

```text
[USE]      style_authority: 设定/文风.md
[FALLBACK] rag: unavailable -> entity_index + summary + prose search
[SKIP]     benchmark: chapter intent does not depend on it
```

### 自定义文风权威

`设定/文风.md` 存在且有实质内容（≥200 字或含声线/句式/用词/禁用腔调小节）时，它是本书文风
第一基准；作者本轮明确指示仍更高。对标文风只能作次级结构参考，冲突时不得覆盖作者文风。
文风文件只是占位时，报告不足并从近期已发生正文提取可观察基线，不因对标缺失而硬停。

## 放行协议

1. 检查上一章事务是否完整；不完整则恢复，不进入本章。
2. 顺序检查四项 required context；任一 MISS 立即返回 `required_context_missing`。
3. 形成章意图并过 beat 预算门；不足返回 `outline_underfilled` 和具体 `missing_beat_budget`。
4. 只检查本章实际需要的 conditional context，逐项记 USE/FALLBACK/SKIP。
5. 输出采用的权威来源与最后有效 checkpoint。
6. 只有以上通过才输出 `[READY] chapter {N}`，进入场景单元编排。

## 可恢复 checkpoint 与失败码

| Code | Checkpoint | Remediation |
|---|---|---|
| `required_context_missing` | 上一完整章事务 | 补指定文件/字段，复核该项后继续 |
| `outline_underfilled` | 已验证 required context + 未落盘章意图 | 补 beats 或授权缩短目标，不产生正文 |
| `state_conflict` | 冲突前的上下文包 | 按权威顺序裁决；不足时请作者选择 |
| `tool_unavailable` | 最近不依赖该工具的阶段 | 人工回退并记录；硬前提不可替代时停止 |
| `gate_blocked` | 门禁前 pending draft | 最多两轮定向修复后交作者决定 |
| `transaction_incomplete` | 上一 canonical state | 恢复快照，不开始下一章 |

恢复时只重验失败项及其依赖，不重写已经通过的章意图或正文阶段。

## 日更质量门

每章仍须一章一闭环：

1. pending draft 运行 `check_text.py`、`rhythm_guard.py`，按需运行文风指纹比较。
2. 按 `chapter-loop.md` 自查；短促高潮与对白允许短句，非峰值叙述必须保留清楚的指代、因果和
   自然句群。
3. 在同一 stage 暂存章节摘要、角色状态、伏笔台账、时间线、节奏配额；运行事务 validate，
   使正文、五表、gate 与实体索引来自同一版本，真实自查通过后才 commit。
4. blocking 未清零或事务未提交，不得开始下一章。

## 最小检查单

```text
日更写前 · 第 N 章
[ ] 上一章正文与追踪处于同一完成状态
[ ] 当前章纲存在且授权 beats 足够
[ ] 前章承接已核对
[ ] 出场人物最新状态已核对
[ ] 相关伏笔/时间线/世界硬约束已核对或明确 none
[ ] conditional context 均记录 USE/FALLBACK/SKIP
[ ] 权威冲突已裁决或停止等待作者
[ ] checkpoint 已记录
```
