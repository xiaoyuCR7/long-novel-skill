# Beat Sheet 多步流水线（beat-pipeline）

单次生成长章节时，AI 容易压缩剧情、跳过细节、一笔带过。Beat Sheet 通过拆分步骤
强制每个场景充分展开——把一章拆成若干 Beat（分镜），逐 Beat 扩写再串合。

## 何时启用

满足以下任意一条即启用 Beat Sheet，不用走标准单章循环的 Step 4：

- 高潮章（快档，触发 A/B/C 配额）
- 反转章（认知颠覆，信息量大）
- 大结算章（卷末/终局）
- 字数 >4000 字的长章
- 单章门禁连续 2 次失败的章

日常日更章不强制启用，按 `chapter-loop.md` 单 Agent 循环即可。

## Step 1：生成 Beat Sheet

读章纲 → 拆解成 Beat（分镜）。一个章拆 4–8 个 Beat，总字数预算 = 章纲字数预算。
每个 Beat 按以下模板写：

```markdown
## Beat {N}：{Beat 名称}
- 场景：{地点/时间}
- 出场人物：{}
- 核心动作：{这一拍发生什么}
- 目标情绪：{读者应该感到什么}
- 字数预算：{}字
- 钩子：{Beat 末尾留什么（最后一个 Beat 的钩子 = 章尾钩子）}
```

Beat Sheet 产出存入 `大纲/beat-sheet_第XXX章.md`。Beat 颗粒度：一个 Beat = 一个场景
或一次情绪转折，不要拆太碎（拆到每句 = 失去场景完整性）。

## Step 2：节奏预检

Beat Sheet 定稿前先查三件事，越界就改 Beat Sheet 不改正文：

- **Beat 节奏分布**：是否有连续 3 个以上同类型 Beat（全是对话/全是打斗）？
  有 = 节奏单调，插入异类型 Beat。
- **A/B/C 配额**：Beat 中触发了几项？>1 = 越界，改 Beat Sheet 把多余项挪到后续章
  （参照 `craft/reverse-brake.md`）。
- **事件冷却**：本章的主事件类型是否在冷却期内？在 = 改 Beat 换事件类型。

## Step 3：逐 Beat 扩写

按 Beat 顺序逐个扩写，每个 Beat 作为独立生成单元：

- 只给写作 Agent 当前 Beat + 上下文速记（前一个 Beat 的末尾段落）
- 每个 Beat 写完后：跑 `check_text.py` 检查这段（字数/禁用词/7 Gate）
- Beat 之间的过渡：用动作/场景切换，不用「与此同时」或「另一边」

逐 Beat 扩写的好处：单次生成上下文短，AI 不会为了赶进度而压缩场景。
坏处是过渡容易生硬，Step 4 专门处理。

## Step 4：串联合成

把所有 Beat 的正文按顺序拼接，检查三件事：

- **过渡自然度**：Beat 之间是否生硬？生硬处补一句动作/场景切换
- **全章字数**：是否在章纲预算内？超了按 Beat 字数预算找超支 Beat 删减
- **结构四拍**：承接→发展→结算→钩子是否齐全？（参照 `craft/pacing-and-hooks.md`）

合成后产出 `正文/第XXX章_{标题}.md`。

## Step 5：全章门禁

整章合成后跑四项门禁，四项全过才算完成：

```bash
python scripts/check_text.py "正文/第XXX章.md" --min-chars N --max-chars M --gate-report
python scripts/rhythm_guard.py --chapter-file "正文/第XXX章.md" --quota "追踪/节奏配额.md"
python scripts/style_fingerprint.py extract "正文/第XXX章.md" --output tmp_fp.md
python scripts/style_fingerprint.py compare tmp_fp.md "设定/文风锚.md"
```

四项分别查：7 Gate/字数/伏笔、A/B/C 配额与事件冷却、文风指纹提取、文风偏离对比。
任何一项 FAIL 就回到对应 Beat 改，不要在合成稿上零敲碎打。

## Step 6：更新追踪

同 `chapter-loop.md` Step 7：章节摘要、角色状态、伏笔台账、时间线、节奏配额五文件
全部回写后，禁止开写下一章。Beat Sheet 文件保留归档，不删——复盘时用来对照
「计划 vs 实际」。

## Beat Sheet 与编辑团队的关系

Beat Sheet 和编辑团队（`craft/editorial-team.md`）解决不同问题，可组合使用：

| 维度 | Beat Sheet | 编辑团队 |
|---|---|---|
| 解决问题 | 怎么写（拆步骤防压缩） | 谁来写（职责分离防污染） |
| 产物 | 分镜大纲 + 逐 Beat 正文 | Chapter Brief + 写作特工产出 |

组合用法：策划主编出 Beat Sheet → 写作特工逐 Beat 扩写 → 反 AI 编辑全章门禁。
日常章用 Beat Sheet 不用编辑团队，关键章两者叠加。

## Beat Sheet 模板

`大纲/beat-sheet_第XXX章.md` 的文件头：

```markdown
# Beat Sheet：第XXX章 {标题}

- 章纲：大纲/章纲_第XXX章.md
- 节奏档位：{慢/中/快}
- A/B/C 预声明：{至多触发 X 项}
- 全章字数预算：{}-{}字

## Beat 清单
[按 Step 1 模板逐个列出]

## 节奏预检结果
- Beat 类型分布：{}
- A/B/C 触发：{}
- 事件冷却：{}
```
