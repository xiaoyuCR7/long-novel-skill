# 如何使用评测集

这是可运行的评测输入集，不是已通过的模型成绩单。

- `cases.json`：24 个原始任务与评阅标准，三类各8个、三题材覆盖。模型只接收 prepare 输出的输入与 prompt。
- `fictional-world.json`：6 个补充场景，覆盖复生/瞬移的正反例、无代价系统、武道奇观、架空制度与现实资料区分。
- `retrieval.json`：12 个合成文档和12个检索问题，含多证据答案。
- `scripts/skill_eval.py`：校验、准备、记录工件、BM25 合成检索指标。命令从 Skill 根目录运行。

完整流程与证据限制见 `references/workflow/evidence-review.md`。真实运行输出放在工程外新目录，
不能覆盖现有书籍，不把本目录的 criteria 传给被测 Agent。缺少模型调用、轨迹或人工评阅时明确 not_run。

补充集独立运行，默认24例保持不变：

```bash
python scripts/skill_eval.py validate --suite evals/fictional-world.json
python scripts/skill_eval.py prepare F03 "{work}/F03" --suite evals/fictional-world.json
```

准备后的输入不含评阅标准；运行、记录与逐条评阅沿用证据工作流。仅通过6个补充场景不能宣称完整评测通过。
