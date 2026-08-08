# 开书流程（book-init）

从零到「可以开始写第一章」的完整流程。每一步的产物都落在书籍工程目录里；
模板统一从 `assets/templates/` 拷贝后填写，不要原地改模板。
（带已有书稿接手不走本流程，走 `workflow/import-book.md`。）

## Step 0：创意与定位（先聊清楚再动手）

和作者确认以下信息，任何一项缺失都不进入下一步：

- 一句话卖点（这本书看什么？）
- 主题材（+ 可选辅题材）→ 决定加载哪张题材卡
- 目标平台（番茄/起点/晋江/知乎盐言/番茄短篇/其他）→ 决定章长与更新排产
- 目标总字数与更新计划（日更几章、每章多少字）
- 读者契约三要素：核心快感、兑现频率、红线（绝不写什么）→ 详见 `craft/reader-contract.md`
- 对标作品（1–3 本，没有可跳过）

产物：创建书籍工程目录（结构见 `assets/templates/book-structure.md`），
把以上信息填进 `设定/题材定位.md`（模板：`assets/templates/genre-profile.md`）
和 `设定/读者契约.md`（模板：`assets/templates/reader-contract.md`）。

## Step 1：一键建骨架（init_book.py）

把 Step 0 的「目录骨架 + 模板拷贝」从手工活变成一条命令：

```bash
python scripts/init_book.py "{书名}" --genre {主题材} --platform {目标平台}
# 指定父目录：--dir "D:/存放/小说"
# 目录已存在且非空时加 --force 重建缺失模板（不动 正文/ 与 大纲/）
```

脚本会按 `assets/templates/book-structure.md` 的布局创建：

```
{书名}/
├── 大纲/  正文/  对标/  参考资料/
├── 设定/  题材定位.md（已轻量预填书名/主题材/平台）、读者契约.md、文风锚.md、敏感词替换表.md、禁用词.txt、角色/
├── 追踪/  伏笔台账.md、角色状态.md、章节摘要.md、时间线.md、节奏配额.md、门禁/
└── .deslop-whitelist（白名单模板）
```

五个追踪文件 + 三个设定文件均从 `assets/templates/` 原样拷贝；
`设定/题材定位.md` 已按传入的书名/主题材/平台做了轻量预填，其余字段留占位待 Step 2–5 填写。

> 也可手工创建目录与拷贝模板，但推荐用脚本——保证路径与文件名约定一致，
> 下游 `resume.py` / `validate_tracking.py` / `entity_index.py` 等都依赖这套约定。

骨架建好后，按 SKILL.md 的题材包加载协议，从 `references/genres/INDEX.md`
匹配并读入主题材卡；读 `references/platforms/platform-guide.md` 中目标平台的基线。
这两份规则贯穿开书全程：世界观、总纲、章纲都要在它们的约束下做。
**有对标书时，先拆再写**：抽读对标书前/中/后段各几章，记录爽点分布、钩子位置、
段落特征（可用 `scripts/check_text.py --style-stats` 量化），产出本书的差异化打法，
填进题材定位的「对标与差异化」，并为 Step 2 的文风锚积累参数。

## Step 2：世界观、人物与文风

- `设定/世界观.md`：只写「不写就会崩」的部分——世界运转的核心规则、力量/财富/权力体系、
  地理与势力格局。细则随写随补，不要开书就写十万字设定。
- `设定/角色/{角色名}.md`：先做主角，再做 2–5 个核心配角（模板：`character-card.md`）。
  人物卡重点写「不变量」（核心性格、底线、口癖），写法见
  `references/craft/character-consistency.md`。
- `设定/敏感词替换表.md`（模板：`sensitive-word-replacement.md`）：**与世界观同步建**——
  世界观里出现的每个地理/机构/人物名，逐一问「这是不是真实世界的东西」，是 → 登记真实
  指称与全书代称。覆盖三块：地名代称系统、别称置换规则（机构/职务/群体）、地名脱敏处理
  方法（模糊化/架空化/时间脱敏）。都市现实向、历史、军事、娱乐圈、官场商战等高敏题材必建，
  纯架空奇幻可只留表头待用。没有这张表，不开写正文第一行。
  方法论见 `references/craft/sensitive-word-replacement.md`；把必禁真实专名并入
  `禁用词.txt` 可让 `check_text.py` 自动拦截（机器核对）。
- `设定/禁用词.txt`：把已加载题材卡的「专属禁用词」一节拷入（机器闸口自动加载）；
  作者有个人的避讳词也一并写入。
- `设定/文风锚.md`（模板：`style-anchor.md`）：作者有样章就从样章反推量化基线；
  没有就先填「腔调关键词」与「不用的腔调」，前 3–5 章写完后补量化基线与样板段落。
  量化基线可用 `scripts/style_fingerprint.py extract` 提取。

## Step 3：总纲

填 `大纲/总纲.md`（模板：`outline-master.md`）：主线一句话、分卷规划表、终局方向、
红线、读者契约摘要、终局储备边界。总纲不求细，求方向不错；它是之后所有卷纲的锚。
方法见 `references/workflow/outline-system.md`。

## Step 4：首卷卷纲 + 首批章纲

- 填 `大纲/卷纲_第1卷.md`（模板：`outline-volume.md`）：本卷契约、剧情单元划分、
  情绪弧线、本卷伏笔计划、大纲锚点配额、卷级档位规划草表。
- 填首批章纲 `大纲/章纲_第001章.md` 起（模板：`outline-chapter.md`），**首批 5–10 章即停靠**，
  不要一口气排完整卷——写完第一批后根据实际情况滚动补纲（见 `outline-system.md`）。
  每份章纲须声明节奏档位与 A/B/C 配额预声明。
- 前三章的章纲按 `references/craft/opening.md` 的黄金三章要求设计，
  开篇强度按「全书中等以上」排产。

## Step 5：初始化追踪文件

`init_book.py` 已经把五个追踪文件骨架拷好，这里做内容初始化（模板：`foreshadowing-ledger.md`、
`character-state.md`、`chapter-summary.md`、`timeline.md`、`rhythm-quota.md`）：

- 角色状态：把 Step 2 的人物卡转成各角色的初始状态条目。
- 伏笔台账：登记开书就计划埋设的开篇伏笔。
- 章节摘要、时间线：建好骨架，待写后填充。
- 节奏配额：建好骨架（模板：`rhythm-quota.md`），含 A/B/C 配额记录表、
  事件冷却记录表、档位记录表的空表头，待写后逐章追加。

初始化完跑一次格式校验，确认骨架合格（之后每 10 章或新会话首次再校验一次）：

```bash
python scripts/validate_tracking.py "{书名}"
```

## Step 6：停靠点——给作者确认

开书包完成后，向作者汇报一份一页纸摘要：题材定位、主角人设一句话、总纲主线、
第一卷契约、前 5–10 章走向、更新排产。**作者确认后才进入写作**；
作者要改就改在文件里，不要口头说了就算。

## 后续衔接

开书完成后，进入写作阶段，每次开工先跑一次会话恢复：

```bash
python scripts/resume.py "{书名}"
```

它会报告上一章门禁是否通过、追踪文件是否同步、伏笔台账有无 🔴 超期、下一章章纲是否就位。
有欠账先补账，无欠账才开写（铁律第 1 条）。单章写作循环见 `references/workflow/chapter-loop.md`。
