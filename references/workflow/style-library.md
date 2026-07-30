# 风格库跨书复用（style-library）

风格库 = 跨书籍的风格指纹集合，用于多书写作/系列写作/风格迁移场景。
把一本书的文风锚（六维量化 + 腔调关键词 + 锚点片段）导入风格库，后续新书可以直接检索和复用，
无需重新拆文提取。

## 何时使用风格库

| 场景 | 说明 | 触发条件 |
|---|---|---|
| 多书写作 | 同一作者写多本书，希望保持统一的笔名风格 | 写完第一本书后，将其风格导入风格库 |
| 系列写作 | 同一系列（如三部曲）需要一致的叙事腔调 | 系列第一本书定调后导入，后续书直接 apply |
| 风格迁移 | 想换一种腔调写新书，参考某本对标书的文风 | 从对标书的文风锚导入风格库，再 apply 到新书 |
| 风格实验 | 同时尝试几种不同腔调，对比哪种更适合新书 | 分别导入多种风格，apply 到不同草稿，对比效果 |
| 团队协作 | 多人合写需要统一文风基准 | 由主笔创建风格条目，其他人 apply 到各自章节 |

不适用：单本书且无风格复用需求的写作、完全不同的笔名/马甲。

## 风格库结构

```
assets/style_library/
├── index.json              # 风格条目索引（JSON 数组）
└── snippets/               # 锚点片段（每个风格条目一个 .md 文件）
    ├── style-20260728-a1b2c3d4.md
    └── ...
```

### index.json 条目结构

```json
{
  "id": "style-20260728-a1b2c3d4",
  "name": "冷酷修仙风",
  "source_book": "我的修仙书",
  "source_path": "D:/存放/小说/我的修仙书/设定/文风锚.md",
  "genre": "玄幻修仙",
  "tags": ["冷峻", "快节奏", "男频"],
  "metrics": {
    "avg_sent_len": 18.5,
    "dialogue_ratio": 35.2,
    "median_para_len": 45,
    "punct_rhythm": {"q": 2.1, "e": 4.3, "ellipsis": 1.5},
    "sentence_pattern": {"alternation_ratio": 0.85, "short_count": 120, "long_count": 141},
    "top_words": [["修炼", 45], ["灵力", 38], ["突破", 32], ...]
  },
  "snippet_path": "assets/style_library/snippets/style-20260728-a1b2c3d4.md",
  "created_at": "2026-07-28T10:00:00Z",
  "notes": "从第1-5章提取的基线"
}
```

## 导入流程

### Step 1：确认源书有文风锚

源书必须已有 `设定/文风锚.md`（由 `style_fingerprint.py extract` 生成）或 `设定/文风指纹.md`。
如果没有，先对源书样章提取：

```bash
python scripts/style_fingerprint.py extract "正文/第001章.md" "正文/第002章.md" \
  --output "设定/文风锚.md"
```

### Step 2：导入风格库

```bash
# 基本导入（自动提取题材和书名）
python scripts/style_library.py import "D:/存放/小说/我的修仙书"

# 带标签和备注
python scripts/style_library.py import "D:/存放/小说/我的修仙书" \
  --name "冷酷修仙风" \
  --genre "玄幻修仙" \
  --tags "冷峻,快节奏,男频" \
  --notes "从第1-5章提取的基线，适合爽文路线"
```

脚本自动完成：
1. 解析 `设定/文风锚.md` 或 `设定/文风指纹.md`，提取六维指标
2. 从 `设定/题材定位.md` 自动提取题材（如果未指定 --genre）
3. 提取锚点片段，保存到 `snippets/` 目录
4. 生成唯一 ID，写入 `index.json`

### Step 3：验证导入结果

```bash
python scripts/style_library.py list
python scripts/style_library.py search --keyword "修仙"
```

## 检索流程

### 按题材搜索

```bash
python scripts/style_library.py search --genre "玄幻"
python scripts/style_library.py search --genre "都市"
```

### 按标签搜索

```bash
python scripts/style_library.py search --tag "冷峻"
python scripts/style_library.py search --tag "热血,快节奏"
```

### 按关键词搜索

```bash
python scripts/style_library.py search --keyword "爽文"
```

### 组合搜索

```bash
python scripts/style_library.py search --genre "玄幻" --tag "冷峻" --limit 5
```

### 预览详情

在搜索结果中找到目标条目后，可以通过 `snippet_path` 查看锚点片段：

```bash
# 查看锚点片段（直接读文件）
cat assets/style_library/snippets/style-20260728-a1b2c3d4.md
```

或者导出为 JSON 查看完整数据：

```bash
python scripts/style_library.py search --genre "玄幻" --format json
```

## 应用流程

### Step 1：选择目标风格条目

通过 search 子命令找到要应用的风格条目 ID：

```bash
python scripts/style_library.py search --genre "玄幻" --tag "冷峻"
# 输出：style-20260728-a1b2c3d4
```

### Step 2：应用到新书

```bash
python scripts/style_library.py apply "style-20260728-a1b2c3d4" \
  --target "D:/存放/小说/新书"
```

脚本自动完成：
1. 从风格库索引中读取目标条目的六维指标和锚点片段
2. 生成 `设定/文风锚.md`（包含量化基线、高频词、腔调关键词、锚点片段）
3. 如果目标目录的 `设定/` 不存在，自动创建

### Step 3：手工校准

应用后需人工确认的内容（脚本不会自动填写）：

| 待确认项 | 位置 | 操作 |
|---|---|---|
| 腔调关键词 | 设定/文风锚.md > 腔调关键词 | 3 个词定义新书腔调，从风格库的标签中参考但不照搬 |
| 不用的腔调 | 设定/文风锚.md > 腔调关键词 | 明确新书不会用的腔调 |
| 高频词白名单 | 设定/文风锚.md > 高频词白名单 | 新书合理的高频词 |
| 样板段落 | 设定/文风锚.md > 锚点片段 | 风格库带的锚点片段是对标书的，新书写完前5章后应替换为自己的 |

### Step 4：新书前5章写完后重新校准

风格库的量化基线是来源书的，新书在实际写作中会产生自己的文风特征。
前5章写完后，用新书自己的样章重新提取基线：

```bash
python scripts/style_fingerprint.py extract "正文/第001章.md" "正文/第002章.md" \
  --output "设定/文风锚.md"
```

这会覆盖风格库 apply 的内容，用新书自己的数据校准。

## 风格库维护

### 列出所有条目

```bash
python scripts/style_library.py list
python scripts/style_library.py list --format json
```

### 删除条目

```bash
# 确认后删除
python scripts/style_library.py delete "style-20260728-a1b2c3d4"

# 强制删除
python scripts/style_library.py delete "style-20260728-a1b2c3d4" --force
```

### 定期清理建议

| 操作 | 频率 | 说明 |
|---|---|---|
| 审查条目 | 每季度 | 检查是否有不再使用的风格条目，删除过时的 |
| 补充标签 | 每次导入后 | 确保标签准确反映风格特征，方便后续检索 |
| 更新六维 | 来源书有新章节后 | 如果来源书的写作风格在长篇中发生了变化，可用新样章重新导入 |
| 备份索引 | 每月 | 备份 `index.json` 和 `snippets/` 目录 |

### 版本管理

风格库的索引文件 `index.json` 是纯 JSON，适合用 Git 管理：

```bash
git add assets/style_library/index.json
git add assets/style_library/snippets/
git commit -m "风格库：导入冷酷修仙风"
```

建议操作：
- 每次导入/删除后提交一次
- 为重要的风格条目打 tag（如 `style-v1-cold-cultivation`）
- 团队成员通过 git pull 同步风格库

## 与上下游文件的对接

### 输入文件（导入前必须存在）

| 文件 | 来源 | 用途 |
|---|---|---|
| `设定/文风锚.md` | `style_fingerprint.py extract` 产出 | 风格指纹的源数据 |
| `设定/题材定位.md` | `book-init.md` 产出 | 自动提取题材 |

### 输出文件（apply 后产出）

| 文件 | 写入时机 | 内容 |
|---|---|---|
| `设定/文风锚.md` | apply 时 | 从风格库导入的六维基线 + 腔调关键词 + 锚点片段 |

### 衔接文件

- **`scripts/style_fingerprint.py`**：风格库依赖其 `parse_anchor_md()` 和 `format_anchor_md()` 函数
- **`references/craft/style-fingerprint.md`**：六维文风指标的定义和校准方法
- **`references/workflow/imitation.md`**：仿写工作流中的风格提取步骤
- **`references/workflow/book-init.md`**：开书流程中的文风锚建立步骤

## 常见问题

### Q: 风格库的六维指标和文风锚的六维指标有什么区别？

风格库存储的是来源书的六维指标（不可变），apply 到新书后，新书的 `设定/文风锚.md` 初始值
等于风格库的指标。新书写完前5章后，应该用 `style_fingerprint.py extract` 重新提取新书
自己的基线，此时风格库的指标仅作为「参考值」保留在文风锚的注释中。

### Q: 同一本书的不同阶段可以导入多个风格条目吗？

可以。如果一本书在长篇写作中文风发生了自然演变（如前期冷峻、后期更温情），可以分阶段导入。
建议命名区分：`我的书-前期`、`我的书-后期`，并在 tags 中标注阶段。

### Q: 风格库可以跨平台使用吗？

可以。风格库是纯本地文件，`index.json` 和 `snippets/` 目录可以复制到其他机器。
跨平台路径问题：`source_path` 字段存储的是绝对路径，复制到其他机器后该字段可能失效，
但不影响核心功能（六维指标和锚点片段不依赖源路径）。