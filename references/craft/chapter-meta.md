# 章节元数据侧车规范（chapter-meta）

每章写完生成一份独立的元数据文件（JSON），作为章节的「结构化索引」。
元数据文件不进入正文，不干扰阅读——它是侧车（sidecar），与正文并行存在，
供下游工具和 Agent 消费。

## 元数据文件位置

```
追踪/chapter_meta/第XXX章.meta.json
```

- `XXX` 为三位数章节号（如 `第001章.meta.json`、`第137章.meta.json`）
- 文件名与正文文件名严格对应（正文为 `正文/第XXX章.md`，元数据为 `追踪/chapter_meta/第XXX章.meta.json`）
- 每章一个独立文件，不合并（方便增量更新和并行读取）

## 元数据 Schema

```json
{
  "schema_version": 1,
  "chapter": {
    "number": 1,
    "title": "第一章标题",
    "word_count": 3200,
    "pacing_tier": "fast",
    "trigger_quota": {
      "A": 1,
      "B": 0,
      "C": 0
    }
  },
  "key_entities": {
    "characters": ["主角A", "配角B"],
    "locations": ["宗门大殿", "后山"],
    "items": ["灵石", "古剑"],
    "factions": ["青云宗", "魔教"]
  },
  "emotion_tags": {
    "primary": "怒",
    "secondary": ["喜"],
    "arc_type": "V形",
    "arc_stage": "爆发",
    "demand_type": "爽"
  },
  "foreshadowing": {
    "planted": [
      {
        "id": "F001",
        "description": "古剑上的铭文似乎缺了一角",
        "intensity": "low",
        "expected_payoff_chapter": null
      }
    ],
    "paid_off": ["F003"],
    "in_progress": ["F001", "F002"]
  },
  "character_appearances": [
    {
      "name": "主角A",
      "role": "protagonist",
      "screen_time": "main",
      "status_change": "从重伤恢复到全盛",
      "emotion_arc": "压抑→爆发"
    },
    {
      "name": "配角B",
      "role": "ally",
      "screen_time": "supporting",
      "status_change": null,
      "emotion_arc": "旁观→震惊"
    }
  ],
  "scenes": [
    {
      "id": 1,
      "location": "宗门大殿",
      "summary": "主角在宗门大殿接受考核",
      "word_count": 1200,
      "pacing": "fast",
      "emotion_primary": "怒",
      "key_event": "主角击败考官"
    },
    {
      "id": 2,
      "location": "后山",
      "summary": "主角独自在后山修炼，发现古剑异常",
      "word_count": 800,
      "pacing": "slow",
      "emotion_primary": "惊",
      "key_event": "古剑铭文发光"
    }
  ],
  "causal_chain": {
    "from_previous": "第001章结尾主角受重伤→第002章开篇主角恢复中接受考核",
    "to_next": "第002章结尾古剑发光→第003章开篇古剑中的前辈残魂苏醒"
  },
  "hook": {
    "type": "悬念型",
    "description": "古剑发光后，剑中传来一声苍老的叹息",
    "intensity": "high"
  },
  "generated_at": "2026-07-28T12:00:00+08:00",
  "generated_by": "chapter_meta.py"
}
```

### 字段说明

#### chapter（章节基础信息）

| 字段 | 类型 | 说明 |
|---|---|---|
| `number` | int | 章节号，从 1 开始 |
| `title` | string | 章节标题 |
| `word_count` | int | 正文字数（不含元数据） |
| `pacing_tier` | string | 节奏档位：`fast`/`mid`/`slow` |
| `trigger_quota` | object | A/B/C 触发配额消耗情况。`A`/`B`/`C` 为本章消耗的各类触发配额数量 |

#### key_entities（关键实体）

本章中出现的所有关键实体，用于 `entity_index.py` 构建语义索引。

| 字段 | 类型 | 说明 |
|---|---|---|
| `characters` | string[] | 本章出场的角色名（使用角色在 `设定/角色/` 中的规范名称） |
| `locations` | string[] | 本章出现的场景/地点 |
| `items` | string[] | 本章出现的关键物品/道具 |
| `factions` | string[] | 本章涉及的势力/组织 |

#### emotion_tags（情绪标记）

本章的情绪分类，用于 `story_graph.py` 构建情绪图谱和跨章情绪分析。

| 字段 | 类型 | 说明 |
|---|---|---|
| `primary` | string | 主情绪类型：爱/恨/惧/悲/怒/喜/惊/耻（见 `emotional-arc.md` 八大类） |
| `secondary` | string[] | 次情绪类型（1-2 个） |
| `arc_type` | string | 情绪弧线类型：V形/倒V形/W形/递进/延迟满足/急转 |
| `arc_stage` | string | 本章在弧线中的阶段：蓄积/爆发/余韵/过渡/高点/低谷 |
| `demand_type` | string | 读者需求类型：爽/虐/甜/燃/悬疑 |

#### foreshadowing（伏笔操作）

本章的伏笔状态变化，用于 `foreshadowing.py` 追踪伏笔生命周期。

| 字段 | 类型 | 说明 |
|---|---|---|
| `planted` | object[] | 本章新埋的伏笔。`id` 为伏笔编号（F+三位数字），`description` 为伏笔描述，`intensity` 为烈度（low/mid/high），`expected_payoff_chapter` 为预计回收章（可 null） |
| `paid_off` | string[] | 本章回收的伏笔 ID 列表 |
| `in_progress` | string[] | 截至本章仍在进行中的伏笔 ID 列表（= 上一章的 in_progress + 本章 planted - 本章 paid_off） |

#### character_appearances（角色出现）

本章每个出场角色的详细状态，用于 `character_state.py` 追踪角色弧线。

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 角色名（规范名称） |
| `role` | string | 角色类型：protagonist/ally/antagonist/neutral/cameo |
| `screen_time` | string | 出场分量：main（主角章）/supporting（重要配角）/cameo（客串） |
| `status_change` | string\|null | 本章中角色的状态变化描述（如「从重伤到恢复」「从友好到敌对」），无变化则为 null |
| `emotion_arc` | string | 本章中该角色的情绪弧线描述（如「平静→愤怒→爆发」） |

#### scenes（场景列表）

本章的场景切分，用于 `story_graph.py` 构建场景流转图。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 场景序号，从 1 开始 |
| `location` | string | 场景地点 |
| `summary` | string | 场景摘要（一句话） |
| `word_count` | int | 场景字数 |
| `pacing` | string | 场景内节奏：fast/mid/slow |
| `emotion_primary` | string | 场景主情绪（八大类之一） |
| `key_event` | string | 场景的关键事件（一句话） |

#### causal_chain（因果链）

本章与前章/后章的因果关联，用于 `resume.py` 会话恢复时快速定位上下文。

| 字段 | 类型 | 说明 |
|---|---|---|
| `from_previous` | string | 前章结尾 → 本章开篇的因果链（如「第N章结尾X→第N+1章开篇Y」） |
| `to_next` | string | 本章结尾 → 下一章预期的因果链（如「第N+1章结尾X→第N+2章预期Y」） |

衔接设计方法论（因果链三型 / 四类过渡元素 / 动机连贯 / 呼应预示）见
`references/craft/chapter-junction.md`；两栏内容与 `章节摘要.md` 的「承上 / 启下」一致。

#### hook（章末钩子）

本章章末钩子的类型和强度，用于 `pacing-and-hooks.md` 的钩子追踪。

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | string | 钩子类型：悬念型/反转型/冲突型/疑问型/情感型/信息型 |
| `description` | string | 钩子内容描述（一句话） |
| `intensity` | string | 钩子强度：high/mid/low |

---

## 元数据生成时机

**每章正文写完 + 追踪文件更新后**，立即生成该章的元数据文件。

标准流程（在 `workflow/chapter-loop.md` 中定义）：

```
写完正文 → 更新追踪文件（伏笔台账/角色状态/章节摘要/时间线/节奏配额）
         → 跑 chapter_meta.py 生成本章元数据
         → 门禁检查（validate_tracking.py）
         → 进入下一章
```

元数据生成必须紧接在追踪文件更新之后——因为元数据是对追踪文件的「结构化摘要」，
如果追踪文件还没更新，元数据会缺失信息。

## 元数据的消费方

元数据文件被以下工具和 Agent 消费：

### entity_index.py（语义检索）

- **消费字段**：`key_entities`、`scenes[].location`
- **用途**：构建「实体→出现章节」的倒排索引。当 Agent 需要查找「某个角色在哪些章
  节出现过」「某个地点在哪些章节被使用」时，直接从 entity_index 中检索，不用遍历
  所有正文。
- **更新时机**：每次新章元数据生成后，重新构建索引（增量更新或全量重建）。

### story_graph.py（图谱构建）

- **消费字段**：`emotion_tags`、`scenes`、`causal_chain`、`hook`
- **用途**：构建章节级叙事图谱——情绪曲线可视化、场景流转图、因果链网络、钩子链。
  用于跨章分析（如「检测情绪弧线是否完整」「钩子密度是否达标」「因果链是否断裂」）。
- **更新时机**：每次新章元数据生成后，更新图谱。

### resume.py（会话恢复）

- **消费字段**：`causal_chain`、`key_entities`、`chapter.word_count`、`hook`
- **用途**：当 Agent 会话中断后恢复时，通过元数据快速定位上下文——不用重读正文，
  直接读最近几章的因果链和关键实体，就能恢复写作状态。
- **更新时机**：实时读取（每次恢复时读取最新章的元数据）。

### 跨 Agent 审核

- **消费字段**：全部字段
- **用途**：当审核 Agent（如 `cross-review.md` 中定义的审核流程）需要检查某章
  是否符合规范时，直接读元数据做结构化校验——不需要解析正文。
- **典型校验**：
  - 章尾钩子强度是否达标（`hook.intensity` 不能是 `low` 如果本章是快档章）
  - 情绪需求类型是否连续 3 章相同（`emotion_tags.demand_type` 连续相同触发警报）
  - 伏笔是否超期未回收（`foreshadowing.in_progress` 中超过 30 章未回收的伏笔）
  - 角色出场分量是否合理（主角连续 3 章不出场触发警报）

---

## 轻量生成脚本 chapter_meta.py 接口规范

`chapter_meta.py` 是生成元数据文件的轻量脚本。本节只定义接口规范，不实现完整脚本。

### 命令行接口

```bash
python scripts/chapter_meta.py generate \
  --chapter-number 137 \
  --chapter-file "正文/第137章.md" \
  --tracking-dir "追踪/" \
  --output "追踪/chapter_meta/第137章.meta.json"
```

### 参数说明

| 参数 | 必填 | 说明 |
|---|---|---|
| `--chapter-number` | 是 | 章节号（整数） |
| `--chapter-file` | 是 | 正文文件路径 |
| `--tracking-dir` | 是 | 追踪文件目录（用于读取伏笔台账、角色状态等） |
| `--output` | 否 | 输出路径（默认：`追踪/chapter_meta/第{chapter-number}章.meta.json`） |

### 生成逻辑（伪代码）

```python
def generate_meta(chapter_number, chapter_file, tracking_dir):
    # 1. 读取正文文件
    text = read_file(chapter_file)
    word_count = count_chinese_chars(text)
    title = extract_title(text)  # 从正文第一行提取标题

    # 2. 从追踪文件读取上下文
    foreshadowing_ledger = read_json(f"{tracking_dir}/伏笔台账.json")
    character_states = read_json(f"{tracking_dir}/角色状态.json")
    pacing_quota = read_json(f"{tracking_dir}/节奏配额.json")

    # 3. 从章纲读取章纲元数据（如果有）
    outline = read_file(f"大纲/章纲_第{chapter_number:03d}章.md")
    pacing_tier = extract_pacing_tier(outline)  # 从章纲中提取档位声明
    trigger_quota = extract_trigger_quota(outline)  # 从章纲中提取配额消耗

    # 4. 模型推理（需要模型介入的字段）
    key_entities = llm_extract_entities(text)  # 关键实体提取
    emotion_tags = llm_extract_emotion_tags(text)  # 情绪标记
    scenes = llm_split_scenes(text)  # 场景切分
    character_appearances = llm_extract_character_appearances(text, character_states)
    causal_chain = llm_extract_causal_chain(text, chapter_number)
    hook = llm_extract_hook(text)

    # 5. 伏笔操作（从伏笔台账中读取本章的 planted/paid_off）
    foreshadowing = extract_foreshadowing_ops(foreshadowing_ledger, chapter_number)

    # 6. 组装 JSON 并写入
    meta = build_meta_json(...)
    write_json(output_path, meta)
```

### 需要模型推理的字段

以下字段无法通过确定性脚本提取，需要模型（LLM）介入：

- `key_entities`：需要理解语义才能准确提取角色/地点/物品/势力
- `emotion_tags`：需要理解情绪才能准确分类
- `scenes`：需要理解叙事结构才能准确切分场景
- `character_appearances`：需要理解角色弧线才能准确描述状态变化和情绪弧线
- `causal_chain`：需要理解因果逻辑才能准确提取因果链
- `hook`：需要理解叙事意图才能准确识别钩子类型

### 可从追踪文件确定性提取的字段

以下字段不需要模型，直接从追踪文件和章纲中读取：

- `chapter.number`：从文件名或参数中获取
- `chapter.title`：从正文第一行或章纲中获取
- `chapter.word_count`：用 `check_text.py` 统计
- `chapter.pacing_tier`：从章纲的档位声明中读取
- `chapter.trigger_quota`：从章纲的配额消耗中读取
- `foreshadowing`：从伏笔台账中读取本章的 planted/paid_off/in_progress

### 批量生成

```bash
# 为指定范围的章节生成元数据
python scripts/chapter_meta.py batch \
  --from 1 \
  --to 50 \
  --chapter-dir "正文/" \
  --tracking-dir "追踪/" \
  --output-dir "追踪/chapter_meta/"
```

### 增量更新

```bash
# 只为「有正文但缺少元数据」的章节生成元数据
python scripts/chapter_meta.py sync \
  --chapter-dir "正文/" \
  --meta-dir "追踪/chapter_meta/"
```

---

## 元数据质量门禁

每章元数据生成后，`validate_tracking.py` 会对元数据做以下检查：

1. **必填字段完整性**：所有 schema 中定义的字段是否存在且非空
2. **情绪类型合法性**：`emotion_tags.primary` 和 `emotion_tags.secondary` 的值是否在
   八大类（爱/恨/惧/悲/怒/喜/惊/耻）中
3. **弧线类型合法性**：`emotion_tags.arc_type` 是否在六种弧线（V形/倒V形/W形/递进/
   延迟满足/急转）中
4. **因果链完整性**：`causal_chain.from_previous` 和 `causal_chain.to_next` 是否
   非空且有实质内容
5. **钩子强度合理性**：如果 `chapter.pacing_tier` 为 `fast` 且 `hook.intensity` 为
   `low`，触发警告（快档章必须有中高强度钩子）
6. **伏笔 ID 一致性**：`foreshadowing.planted` 中的伏笔 ID 是否与伏笔台账中的记录
   一致；`foreshadowing.in_progress` 是否等于上一章的 `in_progress` + 本章 `planted`
   - 本章 `paid_off`
7. **角色名一致性**：`key_entities.characters` 和 `character_appearances[].name` 中的
   角色名是否与 `设定/角色/` 中的角色文件名一致