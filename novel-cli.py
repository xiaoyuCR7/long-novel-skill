#!/usr/bin/env python3
"""
novel-cli — long-novel-skill 统一命令行入口
让人类作者无需 AI Agent 也能直接使用核心功能

用法:
    python novel-cli.py init "我的修仙传" --genre 玄幻 --platform 番茄
    python novel-cli.py check "正文/第001章_开局.md"
    python novel-cli.py status "我的修仙传"
    python novel-cli.py write "我的修仙传" --chapter 1
    python novel-cli.py score "正文/第001章_开局.md" --chapter 1 --book-dir "我的修仙传"
"""

import sys
import os
import subprocess
from pathlib import Path

# 脚本目录
SCRIPT_DIR = Path(__file__).parent / "scripts"


def run_script(script_name: str, args: list) -> int:
    """运行 scripts/ 下的脚本"""
    script_path = SCRIPT_DIR / f"{script_name}.py"
    if not script_path.exists():
        print(f"错误: 脚本不存在: {script_path}", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(script_path)] + args
    result = subprocess.run(cmd, cwd=os.getcwd())
    return result.returncode


def cmd_init(args):
    """初始化书籍工程"""
    if len(args) < 1:
        print("用法: novel-cli init <书名> --genre <题材> --platform <平台>")
        return 1

    title = args[0]
    rest = args[1:]
    return run_script("init_book", [title] + rest)


def cmd_check(args):
    """文本质量检查（7 Gate）"""
    if len(args) < 1:
        print("用法: novel-cli check <文件路径> [--min-chars N] [--max-chars N] [--gate-report]")
        return 1

    return run_script("check_text", args)


def cmd_status(args):
    """查看书籍工程状态"""
    if len(args) < 1:
        print("用法: novel-cli status <书名目录>")
        return 1

    return run_script("resume", [args[0]])


def cmd_write(args):
    """写作流程编排"""
    if len(args) < 1:
        print("用法: novel-cli write <书名目录> --chapter <章节号>")
        return 1

    book_dir = args[0]
    rest = args[1:]
    return run_script("novel_flow", ["prepare", book_dir] + rest)


def cmd_score(args):
    """质量评分"""
    if len(args) < 1:
        print("用法: novel-cli score <章节文件> --chapter <章节号> --book-dir <书名目录>")
        return 1

    return run_script("quality_score", ["score"] + args)


def cmd_rhythm(args):
    """节奏检查"""
    if len(args) < 1:
        print("用法: novel-cli rhythm <章节文件> [--quota <配额文件>]")
        return 1

    return run_script("rhythm_guard", ["--chapter-file"] + args)


def cmd_deconstruct(args):
    """拆文分析"""
    if len(args) < 1:
        print("用法: novel-cli deconstruct <文件路径> [--output <输出目录>]")
        return 1

    return run_script("deconstruct", args)


def cmd_style(args):
    """文风指纹提取"""
    if len(args) < 1:
        print("用法: novel-cli style <书名目录> [--chapters <范围>]")
        return 1

    return run_script("style_fingerprint", args)


def cmd_outline(args):
    """大纲锚点管理"""
    if len(args) < 2:
        print("用法: novel-cli outline <init|advance|inject|check> <书名目录> [--chapter N]")
        return 1

    return run_script("outline_anchor", args)


def cmd_graph(args):
    """知识图谱管理"""
    if len(args) < 2:
        print("用法: novel-cli graph <build|query|status> <书名目录>")
        return 1

    return run_script("story_graph", args)


def cmd_retrieval(args):
    """统一检索系统（推荐使用，替代 rag/entity 命令）"""
    if len(args) < 2:
        print("用法: novel-cli retrieval <build|query|entities|grep|status|context> <书名目录> [--top N]")
        return 1
    return run_script("retrieval", args)


def cmd_rag(args):
    """RAG检索（已合并至 retrieval，保留向后兼容）"""
    print("[提示] rag 命令已合并至 retrieval。推荐使用: novel-cli retrieval", file=sys.stderr)
    return run_script("rag_retriever", args)


def cmd_event(args):
    """统一事件调度系统（推荐使用，替代 rhythm 命令）"""
    if len(args) < 2:
        print("用法: novel-cli event <check|recommend|record|status|quota> <书名目录> [--chapter N] [--gear 快/中/慢]")
        return 1
    return run_script("event_system", args)


def cmd_gate_repair(args):
    """门禁修复"""
    if len(args) < 2:
        print("用法: novel-cli gate-repair <书名目录> --chapter <章节号>")
        return 1

    return run_script("gate_repair", args)


def cmd_beat(args):
    """Beat Sheet生成"""
    if len(args) < 2:
        print("用法: novel-cli beat <generate|expand|validate> <书名目录> --chapter <章节号>")
        return 1

    return run_script("beat_sheet_generator", args)


def cmd_normalize(args):
    """标点归一化"""
    if len(args) < 1:
        print("用法: novel-cli normalize <文件路径> [--check]")
        return 1

    return run_script("normalize_punct", args)


def cmd_validate(args):
    """追踪文件验证"""
    if len(args) < 1:
        print("用法: novel-cli validate <书名目录>")
        return 1

    return run_script("validate_tracking", args)


def cmd_test(args):
    """运行测试套件"""
    return run_script("tests/run_tests", args if args else [])


def cmd_mcp(args):
    """启动MCP Server"""
    mcp_script = Path(__file__).parent / "mcp_server" / "server.py"
    if not mcp_script.exists():
        print("错误: MCP Server脚本不存在", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(mcp_script)] + args
    result = subprocess.run(cmd)
    return result.returncode


def cmd_prepare(args):
    """写前准备全流程（大纲锚点+上下文+检索+事件推荐）"""
    return run_script("novel_flow", ["prepare"] + args)


def cmd_track(args):
    """写后追踪更新（验证+索引+锚点+事件+图谱）"""
    return run_script("novel_flow", ["track"] + args)


def cmd_daily(args):
    """日更批量模式（串行 prepare→check→track）"""
    return run_script("novel_flow", ["daily"] + args)


def cmd_report(args):
    """进度报告"""
    return run_script("novel_flow", ["report"] + args)


def cmd_revise(args):
    """改纲级联（锚点重算+图谱级联+索引重建）"""
    return run_script("novel_flow", ["revise"] + args)


def cmd_rollback(args):
    """回滚追踪文件到快照"""
    return run_script("novel_flow", ["rollback"] + args)


def cmd_unlock(args):
    """清除执行锁"""
    return run_script("novel_flow", ["unlock"] + args)


def cmd_snapshots(args):
    """列出可用快照"""
    return run_script("novel_flow", ["snapshots"] + args)


def cmd_dashboard(args):
    """启动本地Web工作台"""
    if len(args) < 1:
        print("用法: novel-cli dashboard <书名目录> [--port 8765]")
        return 1
    return run_script("dashboard", args)


def cmd_adaptive(args):
    """自适应写作引擎"""
    return run_script("adaptive_engine", args)


def cmd_package(args):
    """微Skill打包与多平台Plugin生成"""
    return run_script("skill_packager", args)


def show_help():
    """显示帮助"""
    print("""
novel-cli — long-novel-skill 统一命令行入口 v6.1

用法:
    python novel-cli.py <命令> [参数]

命令:
    init          初始化书籍工程
                    novel-cli init "书名" --genre 玄幻 --platform 番茄

    check         文本质量检查（7 Gate）
                    novel-cli check "正文/第001章.md" --gate-report

    status        查看书籍工程状态
                    novel-cli status "书名目录"

    write         写作流程编排
                    novel-cli write "书名目录" --chapter 1

    score         质量评分（七维加权）
                    novel-cli score "正文/第001章.md" --chapter 1 --book-dir "书名目录"

    rhythm        节奏配额检查
                    novel-cli rhythm "正文/第001章.md" --quota "追踪/节奏配额.md"

    deconstruct   拆文分析
                    novel-cli deconstruct "对标书.txt" --output "对标/书名"

    style         文风指纹提取
                    novel-cli style "书名目录" --chapters 1-5

    outline       大纲锚点管理
                    novel-cli outline init "书名目录"
                    novel-cli outline inject "书名目录" --chapter 5

    graph         知识图谱管理
                    novel-cli graph build "书名目录"
                    novel-cli graph status "书名目录"

    rag           RAG检索
                    novel-cli rag build "书名目录"
                    novel-cli rag query "书名目录" --query "主角能力"

    beat          Beat Sheet生成
                    novel-cli beat generate "书名目录" --chapter 5

    gate-repair   门禁修复计划
                    novel-cli gate-repair "书名目录" --chapter 5

    normalize     标点归一化
                    novel-cli normalize "正文/第001章.md" --check

    validate      追踪文件验证
                    novel-cli validate "书名目录"

    test          运行测试套件
                    novel-cli test

    dashboard     启动本地Web工作台
                    novel-cli dashboard "书名目录"
                    novel-cli dashboard "书名目录" --port 9000

    adaptive      自适应写作引擎（根据状态动态调整策略）
                    novel-cli adaptive analyze "书名目录"
                    novel-cli adaptive suggest "书名目录"
                    novel-cli adaptive report "书名目录"

    package       微Skill打包与多平台Plugin生成
                    novel-cli package list-micro-skills
                    novel-cli package list-platforms
                    novel-cli package generate-all --output dist/

    retrieval     统一检索系统（v6.3 新增，推荐）
                    novel-cli retrieval build <书名目录>
                    novel-cli retrieval query <书名目录> "查询文本" --top 4
                    novel-cli retrieval entities <书名目录> 实体名
                    novel-cli retrieval status <书名目录>

    event         统一事件调度系统（v6.3 新增，推荐）
                    novel-cli event check <书名目录> --chapter N --declare "A,conflict,快"
                    novel-cli event recommend <书名目录> --gear 快
                    novel-cli event record <书名目录> --event conflict --chapter N
                    novel-cli event status <书名目录>

    prepare       写前准备全流程（v6.3 新增）
                    novel-cli prepare <书名目录> --chapter N

    track         写后追踪更新（v6.3 新增）
                    novel-cli track <书名目录> --chapter N

    daily         日更批量模式（v6.3 新增）
                    novel-cli daily <书名目录> --chapters 3

    report        进度报告（v6.3 新增）
                    novel-cli report <书名目录>

    revise        改纲级联（v6.3 新增）
                    novel-cli revise <书名目录> --from-chapter 50 --desc "加入新反派"

    rollback      回滚追踪文件到快照（v6.3 新增）
                    novel-cli rollback <书名目录> --snapshot <timestamp>

    unlock        清除执行锁（v6.3 新增）
                    novel-cli unlock <书名目录>

    snapshots     列出可用快照（v6.3 新增）
                    novel-cli snapshots <书名目录>

    mcp           启动MCP Server
                    novel-cli mcp
                    novel-cli mcp --http --port 8000

环境要求:
    Python 3.8+
    无第三方依赖（MCP模式需 pip install mcp）

更多信息:
    SKILL.md          — 完整技能文档
    README.md         — 使用说明
    mcp_server/README.md — MCP Server配置指南
""")


COMMANDS = {
    # 新手高频命令（覆盖80%日常场景）
    "init": cmd_init,          # 开书
    "write": cmd_write,        # 写章
    "check": cmd_check,        # 检查
    "status": cmd_status,      # 状态
    "dashboard": cmd_dashboard, # 看板
    "adaptive": cmd_adaptive,   # 自适应写作
    "score": cmd_score,        # 评分
    "test": cmd_test,          # 测试
    # 编排命令（v6.3 新增）
    "prepare": cmd_prepare,    # 写前准备
    "track": cmd_track,        # 写后追踪
    "daily": cmd_daily,        # 日更批量
    "report": cmd_report,      # 进度报告
    "revise": cmd_revise,      # 改纲级联
    "rollback": cmd_rollback,  # 回滚
    "unlock": cmd_unlock,      # 清锁
    "snapshots": cmd_snapshots, # 快照列表
    # 进阶命令
    "rhythm": cmd_rhythm,      # 节奏检查（兼容）
    "event": cmd_event,        # 事件系统（推荐）
    "deconstruct": cmd_deconstruct,
    "style": cmd_style,
    "outline": cmd_outline,
    "graph": cmd_graph,
    "rag": cmd_rag,            # RAG检索（兼容）
    "retrieval": cmd_retrieval, # 统一检索（推荐）
    "beat": cmd_beat,
    "gate-repair": cmd_gate_repair,
    "normalize": cmd_normalize,
    "validate": cmd_validate,
    "package": cmd_package,     # 微Skill打包
    "mcp": cmd_mcp,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        show_help()
        sys.exit(0)

    command = sys.argv[1]
    args = sys.argv[2:]

    if command not in COMMANDS:
        print(f"错误: 未知命令 '{command}'", file=sys.stderr)
        print(f"可用命令: {', '.join(COMMANDS.keys())}", file=sys.stderr)
        sys.exit(1)

    exit_code = COMMANDS[command](args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
