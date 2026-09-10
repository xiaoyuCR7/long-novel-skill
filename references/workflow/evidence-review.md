# 证据、诊断与评测

只在审核分数、图谱/检索、上下文溢出、修订影响或 Skill 评测时加载本文件。

## 三类证据分别报告

| 证据 | 能说明什么 | 不能据此宣称什么 |
|---|---|---|
| 机器门禁 | 明确规则、格式、追踪与来源哈希的检查结果 | 情感动人、人物可信、文学优秀 |
| 文本统计 | 词频、句长、对话等启发式观察 | 语义审核通过；安静场景必须增加情绪词 |
| 实际语义审阅 | 审阅者基于指定正文和授权来源的可定位结论 | 未读取的其他章节通过或长期连载效果已验证 |

`scripts/quality_score.py` 保留 `total_score`、等级字母和历史 `passed` 以兼容旧调用；
它们只指固定统计阈值 55。`semantic_review.status` 与 `machine_gates.status` 都是 `not_run`，
不能从高分填成 pass。原有 `--threshold` 参数是兼容保留项，不改变阈值。旧 JSON 同样按此边界解释。
情绪词、身体动作的计数可能被堆词抬高；结合章意图、选择代价、关系变化与题材判断，
允许自然内心戏、短回答、长句、闭合结尾以及低冲突但有功能的日常。

## 图谱与改章影响

`scripts/story_graph.py` 的自动关系带 `assertion_kind`、`context_flags`、来源路径、章号、
文本/span 与 SHA-256。即使字面像陈述，仍是 `unconfirmed` 候选；文本出现一句话不证明事实成立。
问句、假设、否定、引语必须带语境。旧格式读作 `legacy_unconfirmed`，源文改变后提示过期。
哈希证明来源是否改变，不证明提取正确；实体无法可靠匹配时漏提优于凭空建人名。

```bash
python scripts/story_graph.py impact "{book}" --chapter {N}
```

影响清单只用于定位回查范围；当前来源提及与图谱/索引可能引用分开呈现，不是自动修稿指令。
检索不到不等于没有影响，缺图谱可直接搜摘要与正文。具体写稿仍走 `revision.md` 章事务。

## 上下文选择回执与旧格式

上下文包的 `selection_receipt` 记录 required 字符数、预算、Brief 大小，以及两张追踪表的
原始/选入/省略字符数、行范围与选择理由。只有明确归档分区可省略；未知标题和遗留平铺文本保留。
`legacy_preserved` 不是“已迁移”，超预算仍须停止，不能悄悄截断。

```bash
python scripts/context_manager.py inspect-state "{book}" --chapter {N} --output "{work}/tracking-candidate.json"
```

`{work}` 必须为已存在的工程外工作目录，目标文件必须不存在。候选包含原文和哈希，
`applied=false`；它是人工整理依据，不是自动批准的替换文件。逐项核对未知记录的有效性，
实际整理追踪前遵守章事务和作者授权。只读诊断可能创建既有读锁文件，不改变正文与追踪。

## 24 个 Agent 场景与结果记录

`evals/cases.json` 包含缺陷 8、干净 8、生成 8，覆盖悬疑、都市、玄幻；案例均为合成输入。
`evals/fictional-world.json` 另有6个虚构世界补充场景；validate/prepare 用 `--suite evals/fictional-world.json` 选择，记录与评阅方式相同。
`criteria` 只给评阅者。以下命令须在 Skill 根目录运行，评测目录必须在 Skill 与真实书籍之外：

```bash
python scripts/skill_eval.py validate
python scripts/skill_eval.py prepare D02 "{work}/D02"
python scripts/skill_eval.py record "{work}/D02" --response "{work}/D02/response.md" --trace "{work}/D02/trace.json" --model "{actual_model}"
python scripts/skill_eval.py retrieval --top-k 5
```

prepare 只物化原始输入和 prompt，不传答案；状态是 `prepared/not_run`。让新的独立 Agent
读取此 Skill 和该目录输入，执行原始用户请求；不要给它案例标签、criteria、补丁背景或期望结果。
记录真实响应、实际读取路径/工具/操作轨迹，以及可获取的模型、耗时、tokens；未知值留空，不能估造。
`{work}/D02/trace.json` 为非空对象数组，每条须有非空 tool 或 action，可附 path、结果或输出证据。
record 核对准备回执与原始输入哈希，输入漂移时拒绝记录；prepare/record 拒绝目录联接、
硬链接工件及位于同时含“大纲”“追踪”的书籍目录下的输出。其他布局仍须调用者明确避开真实书籍。
record 校验文件并记录哈希，但只能证明“已提供工件”，不能独立鉴证模型运行真实性；
`passed=null` 与 `semantic_review=not_run` 保留到单独评阅。观察记录独占写入，重跑用新目录。

评阅者读取 criteria、响应及来源，按每条写出证据和 pass/fail/not_run，放在独立 `{work}/review.md`；
不得把语法检查、模板生成或脚本分数记为模型胜率。建议基线与候选同模型、同参数、同输入，
随机隐藏版本给评阅者；记录错误新增率与干净样本误改率，生成类另由作者匿名比较。
最低先跑 24 个案例各一次；要声称优于基线，至少做配对运行并明确重复数与分歧裁决方式。

`evals/retrieval.json` 是 12 文档/12 问题的小型 BM25 合成夹具。报告 Recall@k、MRR 与来源 ID，
不测真实章节上下文装配，也不代表百万字历史召回。加入实际脱敏工程的同义词、否定、别名、
多章交接与改稿失效问题后，再比较实体检索、BM25 与可选向量；没有实测必要性不引入外部数据库。
