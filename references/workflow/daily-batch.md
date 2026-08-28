# 日更批量写作（daily-batch）

每次会话写 2–3 章（4000–9000 字）的串行批量流程，用于日常日更场景。单章写作逻辑
不变（仍走 `chapter-loop.md`），本文件只管「多章连写时的编排、批次级检查与退化防护」。

## 何时用这个

- 日常日更：一次会话写 2–3 章，保持更新频率。
- 不适用：开书首章、卷末大高潮、关键转折章——这些走单章 `chapter-loop.md` 或
  `beat-pipeline.md`，不进批量模式。

## 前提条件

开写前必须全部满足，任一不满足则先补账再进批量：

1. **开书已完成**：书籍工程目录结构齐全（`大纲/`、`设定/`、`正文/`、`追踪/`），
   `设定/文风锚.md` 已建立，`设定/题材定位.md` 已指定题材。
2. **追踪文件已同步**：最近一章的五个追踪文件（章节摘要/角色状态/伏笔台账/
   时间线/节奏配额）全部回写。
3. **无欠账**：

   ```bash
   python scripts/resume.py "{书籍工程目录}"
   ```

   `resume.py` 退出码为 0（无欠账）才进批量。退出码 1 时按报告先补账：
   修未通过的门禁、补回写追踪文件、处理 🔴 超期伏笔。

## 批量上限

- **单轮最多 3 章**：超过 3 章上下文膨胀，文风漂移和一致性风险急剧上升。
  需要写更多章时，开新一轮会话，重新跑 `resume.py` 确认状态。
- **禁止并发**：多章必须串行，一章完整走完 `chapter-loop.md` 的 Step 0–8 后
  才开下一章。不得同时起草多章正文——并行写作会导致角色状态和伏笔台账冲突。
- 一章的正文与五表必须经 prepare → stage → validate → commit 共同提交，不能用报告完成
  或手动回写五表替代 commit。blocking/P0 两轮修复仍失败即 gate_blocked，停止本批；
  切换团队、Beat、模型或新会话不重置额度，也不能降成 advisory。
- 每章沿用完整章意图的 ending_mode。closed/finale 不强制下章钩子或预告；finale 到此结束
  批次，不为凑满 2–3 章造后续章，也不把配额事件推给不存在的章节。

## 写前准备（每章写前都跑）

每章开写前，在 `chapter-loop.md` 的 Step 1（读章纲）之后、Step 2（检索）之前，
跑三个命令：

```bash
# 1. 获取本章大纲锚点约束（禁止揭露什么 / 必须达成什么 / 阶段定位）
python scripts/outline_anchor.py inject "{书籍工程目录}" --chapter {N}

# 2. 声明本章节奏档位（写章前预检 A/B/C 配额与事件冷却是否违规）
python scripts/rhythm_guard.py --quota "追踪/节奏配额.md" \
  --declare "{配额},{事件类型},{档位}" --chapter {N}
#    例如：--declare "A,conflict_thrill,快"
#    或无触发：--declare "无,world_painting,慢"

# 3. 读取本章章纲
#    大纲/章纲_第{NNN}章.md
```

三条命令的目的：

- `outline_anchor.py inject`：拿到本章的全局进度约束——哪些主线秘密还不能揭、
  哪些卷级目标该在本章或后续达成、当前处于开篇/发展/高潮/终局哪一期。防止
  把长线任务当短线跑（见 `outline_anchor.py` 的阶段定位逻辑）。
- `rhythm_guard.py --declare`：写章前预检声明的档位和配额是否与历史记录冲突
  （A 冷却 2 章 / B 冷却 1 章 / C 冷却 3 章 / 事件冷却 / 连续快档）。预检 FAIL
  时在作者授权范围内先调整章纲的节奏声明，且在 chapter-loop Step 3B prepare 前完成。
- 读取章纲：章纲是本章的第一约束，无章纲不写正文（Iron Law 第 2 条）。

三条命令的输出与章纲一起压成本节速记（`chapter-loop.md` Step 3），再进入检索。

## 串行执行流程

```
┌─ 第 1 章 ─────────────────────────────────────────────┐
│  写前准备（inject + declare + 读章纲）                  │
│  → chapter-loop.md Step 0–8（完整走一遍）              │
│  → stage 五表 + 真实自查 + validate + commit             │
└──────────────────────────────────────────────────────┘
                          ↓ 前一章完成且无欠账
┌─ 第 2 章 ─────────────────────────────────────────────┐
│  写前准备（inject + declare + 读章纲）                  │
│  → chapter-loop.md Step 0–8                            │
│  → stage 五表 + 真实自查 + validate + commit             │
└──────────────────────────────────────────────────────┘
                          ↓
┌─ 第 3 章（如需）──────────────────────────────────────┐
│  同上                                                   │
└──────────────────────────────────────────────────────┘
                          ↓ 批次结束
                    批次级检查（见下节）
```

每章内部完整走 `chapter-loop.md` 的 Step 0–8，不简化、不跳步：

- **Step 0**：欠账门（每章开写前查上一章门禁）。
- **Step 1**：读章纲。
- **写前准备**：inject + declare（本文件新增，插入在 Step 1 与 Step 2 之间）。
- **Step 2–8**：检索 → 完整章意图/预算门 → prepare → stage 正文 → 机器闸口 →
  真实自查 → stage 五表 → validate → commit → 报告。

**串行纪律**：一章 commit 成功且 Step 8（向作者报告）完成后，才开下一章的
Step 0。中间不得交叉——不要在写第 2 章正文时回头改第 1 章的追踪文件。

每章必须使用 `chapter-loop.md` Step 7 的真实 validate/commit 命令；validate 内部对同一
stage 校验五表、机器门禁与实体索引，不另行手工修改 canonical 表或 index。validate 不验证
语义报告，主 Agent 仍须真实自查后才使用 --self-review-confirmed。工作报告留在工程外。

## 批次级检查

整批（2–3 章）全部完成后，跑批次级检查，确认全书状态健康：

```bash
# 1. 追踪文件格式复核（防模型把表格/字段写歪）
python scripts/validate_tracking.py "{书籍工程目录}"

# 2. 重建实体→章节索引（本批各章摘要的「关键实体」聚合进索引）
python scripts/entity_index.py build "{书籍工程目录}"

# 3. 推进大纲锚点指针到本批最后一章
python scripts/outline_anchor.py advance "{书籍工程目录}" --chapter {本批末章号}
#    若本批末章是卷末，加 --volume-end 标记本卷完结：
python scripts/outline_anchor.py advance "{书籍工程目录}" --chapter {N} --volume-end
```

三条命令的作用：

- `validate_tracking.py`：批次级复核五个追踪文件格式。每章写完虽已跑过一次，
  但多章连写后可能有交叉影响（摘要压缩、伏笔状态迁移），批末再跑一次兜底。
  报告格式问题时暂停新章，通过受影响章的修订事务处理，不直接改正式表。
- `entity_index.py build`：批次级重建索引。每章虽已跑过，但批末重建一次确保
  索引与本批全部摘要同步，下一轮日更写前检索能用。
- `outline_anchor.py advance`：把锚点指针推进到本批末章。不推进的话下一轮
  `inject` 拿到的进度约束会停在旧位置。卷末必须加 `--volume-end`。

## 退化防护

多章连写最大的风险是文风退化——写得越多，AI 腔越重，句式越趋同。批末跑量化打分，
与前一批对比，漂移超阈值则暂停日更排查。

```bash
# 本批每章只读量化诊断；已提交 gate 由各章事务生成，不在批末覆盖它
python scripts/check_text.py "正文/第{N}章_标题.md" \
  --min-chars {下限} --max-chars {上限} \
  --ledger "追踪/伏笔台账.md" --current-chapter {N} \
  --gate-report

python scripts/check_text.py "正文/第{N+1}章_标题.md" \
  --min-chars {下限} --max-chars {上限} \
  --ledger "追踪/伏笔台账.md" --current-chapter {N+1} \
  --gate-report
```

各章事务生成的 `追踪/门禁/gate_ch{N}.json` 已含 AI 味分数。批末对比本批各章
的 AI 味分数与前一批同指标的均值：

- **漂移 ≤ 15%**：正常，可继续下一轮日更。
- **漂移 > 15%**：暂停日更。排查方向：
  1. 是否某章偷懒走了套路（Gate B 毒句式命中数飙升）。
  2. 是否文风锚失效（跑 `style_fingerprint.py compare` 对照 `设定/文风锚.md`，
     六维指标哪一维漂了）。
  3. 是否对话声线趋同（Gate E，遮名字认人测试）。
  4. 按 `revision.md` 的章事务修复漂移最严重的章节，验证与真实自查后共同提交，再恢复日更。

漂移基线的建立：开书前 10 章的 AI 味分数均值作为基线。前一批 = 上一轮日更的
各章 AI 味分数均值；首轮日更的「前一批」用开书基线。

## 中途快照

每累计 3 章（可能跨多轮日更），验证追踪文件大小是否增长，防止模型静默写入失败
（写了正文但追踪文件没回写，`resume.py` 又没报出来）。

```bash
# 记录当前追踪文件大小（PowerShell）
Get-Item "追踪/章节摘要.md","追踪/角色状态.md","追踪/节奏配额.md" | 
  Select-Object Name, Length
```

3 章前记录一次文件大小，3 章后再记录一次。任一文件大小没有增长 = 静默写入失败，
立即排查：

- 该文件在最近 3 章是否被实际更新过（检查文件 mtime）。
- 若 mtime 是新的但大小没变：可能模型覆写了相同内容（回写时没追加而是覆盖）。
  跑 `validate_tracking.py` 确认格式，再人工核对最近 3 章的摘要/状态/配额是否
  都在文件里。
- 若 mtime 是旧的：核实应有变化是否缺失；需要补表时用受影响章事务同步五表与索引，
  不直接补写正式表。纯措辞修订或无状态变化不要求文件机械增长。

单轮日更（2–3 章）在批末做一次中途快照即可；连续多轮日更时，每跨满 3 章做一次。

## 与 chapter-loop.md 的关系

`daily-batch` 是 `chapter-loop` 的串行编排器——单章逻辑完全不变，本文件只管
多章之间的编排和批次级检查。

| 关注点 | chapter-loop.md | daily-batch.md |
|---|---|---|
| 单章写作流程 | Step 0–8 完整定义 | 不重复定义，直接引用 |
| 写前节奏预检 | Step 1–2 之间（未显式） | 显式插入 inject + declare |
| 章间衔接 | Step 7 欠账门（一章维度） | 串行纪律：前章完成才开下章 |
| 批次级检查 | 无（只管单章） | validate + entity_index + advance |
| 退化防护 | Step 5 文风指纹（单章维度） | 批末跨批 AI 味分数对比 |
| 中途快照 | 无 | 每 3 章验证追踪文件大小 |

简单说：`chapter-loop.md` 管「一章怎么写」，`daily-batch.md` 管「一次会话怎么连写
多章且不退化」。日常日更走 `daily-batch.md`（编排器）→ 每章内走 `chapter-loop.md`
（单章循环）。
