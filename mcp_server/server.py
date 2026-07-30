#!/usr/bin/env python3
"""
long-novel-skill MCP Server
将小说创作技能封装为MCP Server，支持任何MCP客户端调用

使用方法:
    python server.py                    # stdio模式（默认，用于本地集成）
    python server.py --http --port 8000 # HTTP模式（用于远程服务）
"""

import sys
import json
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, field_validator, ConfigDict

# 添加scripts目录到路径
SCRIPT_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

# 导入所有脚本功能
import common
import config
from check_text import main as check_text_main
from style_fingerprint import main as style_fingerprint_main
from rhythm_guard import main as rhythm_guard_main
from deconstruct import main as deconstruct_main
from outline_anchor import main as outline_anchor_main
from event_matrix import main as event_matrix_main
from entity_index import main as entity_index_main
from story_graph import main as story_graph_main
from research_agent import main as research_agent_main
from style_library import main as style_library_main
from content_expander import main as content_expander_main
from context_manager import main as context_manager_main
from novel_flow import main as novel_flow_main
from quality_score import main as quality_score_main
from beat_sheet_generator import main as beat_sheet_generator_main
from chapter_synthesizer import main as chapter_synthesizer_main
from gate_repair import main as gate_repair_main
from editorial_manager import main as editorial_manager_main
from hooks import main as hooks_main
from rag_retriever import main as rag_retriever_main
from init_book import main as init_book_main
from resume import main as resume_main
from normalize_punct import main as normalize_punct_main
from validate_tracking import main as validate_tracking_main

# 尝试导入mcp
HAS_MCP = False
try:
    from mcp.server.fastmcp import FastMCP, Context
    HAS_MCP = True
except ImportError:
    pass


class ResponseFormat(str, Enum):
    """输出格式"""
    MARKDOWN = "markdown"
    JSON = "json"


# ============ 输入模型定义 ============

class CheckTextInput(BaseModel):
    """文本检查输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    file_path: str = Field(..., description="要检查的文本文件路径")
    min_chars: int = Field(default=2000, description="最小字数要求", ge=0)
    max_chars: int = Field(default=3500, description="最大字数要求", ge=0)
    ledger: Optional[str] = Field(default=None, description="伏笔台账文件路径")
    current_chapter: Optional[int] = Field(default=None, description="当前章节号", ge=1)
    gate_report: bool = Field(default=False, description="是否生成门禁报告")
    deslop: bool = Field(default=False, description="是否启用去AI味模式")


class StyleFingerprintInput(BaseModel):
    """文风指纹提取输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    book_dir: str = Field(..., description="书籍工程目录路径")
    chapters: Optional[str] = Field(default=None, description="章节范围，如'1-5'或'1,3,5'")
    output: Optional[str] = Field(default=None, description="输出文件路径")


class RhythmGuardInput(BaseModel):
    """节奏守卫输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    chapter_file: str = Field(..., description="章节文件路径")
    quota_file: Optional[str] = Field(default=None, description="节奏配额文件路径")
    ledger: Optional[str] = Field(default=None, description="伏笔台账文件路径")
    current_chapter: Optional[int] = Field(default=None, description="当前章节号", ge=1)


class DeconstructInput(BaseModel):
    """拆文分析输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    file_path: str = Field(..., description="要对拆的文本文件路径")
    output_dir: Optional[str] = Field(default=None, description="输出目录")
    full_pipeline: bool = Field(default=False, description="是否使用完整七阶段管道")


class OutlineAnchorInput(BaseModel):
    """大纲锚点输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: init/advance/inject/check", pattern="^(init|advance|inject|check)$")
    book_dir: str = Field(..., description="书籍工程目录路径")
    chapter: Optional[int] = Field(default=None, description="章节号", ge=1)
    quota: Optional[str] = Field(default=None, description="配额类型 A/B/C")


class EventMatrixInput(BaseModel):
    """事件矩阵输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: recommend/record/query", pattern="^(recommend|record|query)$")
    book_dir: str = Field(..., description="书籍工程目录路径")
    event_type: Optional[str] = Field(default=None, description="事件类型")
    chapter: Optional[int] = Field(default=None, description="章节号", ge=1)


class EntityIndexInput(BaseModel):
    """实体索引输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: build/semantic", pattern="^(build|semantic)$")
    book_dir: str = Field(..., description="书籍工程目录路径")
    query: Optional[str] = Field(default=None, description="查询实体名（semantic操作）")


class StoryGraphInput(BaseModel):
    """知识图谱输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: build/query/cascade/impact/export/status", 
                       pattern="^(build|query|cascade|impact|export|status|update)$")
    book_dir: str = Field(..., description="书籍工程目录路径")
    node: Optional[str] = Field(default=None, description="节点名称")


class ResearchInput(BaseModel):
    """联网调研输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: plan/gaps/store", pattern="^(plan|gaps|store)$")
    book_dir: Optional[str] = Field(default=None, description="书籍工程目录路径")
    chapter_goal: Optional[str] = Field(default=None, description="本章目标（gaps操作）")
    genre: Optional[str] = Field(default=None, description="题材（plan操作）")
    topic: Optional[str] = Field(default=None, description="调研主题（plan操作）")


class StyleLibraryInput(BaseModel):
    """风格库输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: import/search/apply/delete/list", 
                       pattern="^(import|search|apply|delete|list)$")
    source_dir: Optional[str] = Field(default=None, description="源书目录（import操作）")
    tags: Optional[str] = Field(default=None, description="标签（import/search操作）")
    style_id: Optional[str] = Field(default=None, description="风格ID（apply/delete操作）")


class ContentExpanderInput(BaseModel):
    """内容扩充输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    book_dir: str = Field(..., description="书籍工程目录路径")
    chapter: int = Field(..., description="章节号", ge=1)
    target_chars: Optional[int] = Field(default=None, description="目标字数")


class ContextManagerInput(BaseModel):
    """上下文管理输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: select/compact", pattern="^(select|compact)$")
    chapter: int = Field(..., description="当前章节号", ge=1)
    book_dir: str = Field(..., description="书籍工程目录路径")


class NovelFlowInput(BaseModel):
    """小说流程输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: status/prepare/write/daily/revise/report", 
                       pattern="^(status|prepare|write|daily|revise|report)$")
    book_dir: str = Field(..., description="书籍工程目录路径")
    chapters: Optional[int] = Field(default=None, description="章节数（daily操作）", ge=1)


class QualityScoreInput(BaseModel):
    """质量评分输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: score/trend", pattern="^(score|trend)$")
    chapter_file: str = Field(..., description="章节文件路径")
    chapter: int = Field(..., description="章节号", ge=1)
    book_dir: str = Field(..., description="书籍工程目录路径")


class BeatSheetInput(BaseModel):
    """Beat Sheet输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: generate/expand/validate", 
                       pattern="^(generate|expand|validate)$")
    book_dir: str = Field(..., description="书籍工程目录路径")
    chapter: int = Field(..., description="章节号", ge=1)


class ChapterSynthesizerInput(BaseModel):
    """章节合成输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    book_dir: str = Field(..., description="书籍工程目录路径")
    chapter: int = Field(..., description="章节号", ge=1)


class GateRepairInput(BaseModel):
    """门禁修复输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    book_dir: str = Field(..., description="书籍工程目录路径")
    chapter: int = Field(..., description="章节号", ge=1)


class EditorialManagerInput(BaseModel):
    """编辑团队管理输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: snapshot/status/intervene", 
                       pattern="^(snapshot|status|intervene)$")
    book_dir: str = Field(..., description="书籍工程目录路径")
    chapter: Optional[int] = Field(default=None, description="章节号", ge=1)


class HooksInput(BaseModel):
    """Hook触发输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: session-start/guard-outline/check-prose/detect-gaps/pre-compact", 
                       pattern="^(session-start|guard-outline|check-prose|detect-gaps|pre-compact)$")
    book_dir: str = Field(..., description="书籍工程目录路径")
    chapter: Optional[int] = Field(default=None, description="章节号", ge=1)
    file: Optional[str] = Field(default=None, description="文件路径（check-prose操作）")


class RAGRetrieverInput(BaseModel):
    """RAG检索输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    action: str = Field(..., description="操作: build/query", pattern="^(build|query)$")
    book_dir: str = Field(..., description="书籍工程目录路径")
    query: Optional[str] = Field(default=None, description="查询内容（query操作）")
    top: int = Field(default=4, description="返回结果数", ge=1, le=10)


class InitBookInput(BaseModel):
    """初始化书籍输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    title: str = Field(..., description="书名")
    genre: str = Field(..., description="题材")
    platform: str = Field(..., description="平台")


class ResumeInput(BaseModel):
    """会话恢复输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    book_dir: str = Field(..., description="书籍工程目录路径")


class NormalizePunctInput(BaseModel):
    """标点归一化输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    file_path: str = Field(..., description="文件路径")
    check: bool = Field(default=False, description="仅检查不修改")


class ValidateTrackingInput(BaseModel):
    """追踪验证输入"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    book_dir: str = Field(..., description="书籍工程目录路径")


# ============ MCP Server 定义 ============

def create_mcp_server():
    """创建并配置MCP Server"""
    if not HAS_MCP:
        raise ImportError("MCP SDK未安装，请运行: pip install mcp")
    
    mcp = FastMCP("long_novel_skill_mcp")
    
    # ============ 文本检查工具 ============
    
    @mcp.tool(
        name="novel_check_text",
        annotations={
            "title": "文本质量检查",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def novel_check_text(params: CheckTextInput) -> str:
        """执行7 Gate质量检查，检测AI腔、毒句式、禁用词、伏笔超期等问题。
        
        这是写作流程的核心闸口工具，在章节完成后运行，确保输出质量达标。
        """
        try:
            args = [params.file_path, "--min-chars", str(params.min_chars), "--max-chars", str(params.max_chars)]
            if params.ledger:
                args.extend(["--ledger", params.ledger])
            if params.current_chapter:
                args.extend(["--current-chapter", str(params.current_chapter)])
            if params.gate_report:
                args.append("--gate-report")
            if params.deslop:
                args.append("--deslop")
            
            result = check_text_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 文风工具 ============
    
    @mcp.tool(
        name="novel_style_fingerprint",
        annotations={
            "title": "文风指纹提取",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def novel_style_fingerprint(params: StyleFingerprintInput) -> str:
        """提取书籍的文风指纹，用于跨书风格复用和一致性检查。"""
        try:
            args = [params.book_dir]
            if params.chapters:
                args.extend(["--chapters", params.chapters])
            if params.output:
                args.extend(["--output", params.output])
            
            result = style_fingerprint_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 节奏工具 ============
    
    @mcp.tool(
        name="novel_rhythm_guard",
        annotations={
            "title": "节奏守卫检查",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def novel_rhythm_guard(params: RhythmGuardInput) -> str:
        """检查章节节奏配额，防止剧情加速和越界。"""
        try:
            args = ["--chapter-file", params.chapter_file]
            if params.quota_file:
                args.extend(["--quota", params.quota_file])
            if params.ledger:
                args.extend(["--ledger", params.ledger])
            if params.current_chapter:
                args.extend(["--current-chapter", str(params.current_chapter)])
            
            result = rhythm_guard_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 拆文工具 ============
    
    @mcp.tool(
        name="novel_deconstruct",
        annotations={
            "title": "拆文分析",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def novel_deconstruct(params: DeconstructInput) -> str:
        """拆解对标书，提取文风、角色、剧情线、节奏等结构化素材。"""
        try:
            args = [params.file_path]
            if params.output_dir:
                args.extend(["--output", params.output_dir])
            if params.full_pipeline:
                args.append("--full-pipeline")
            
            result = deconstruct_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 大纲工具 ============
    
    @mcp.tool(
        name="novel_outline_anchor",
        annotations={
            "title": "大纲锚点管理",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def novel_outline_anchor(params: OutlineAnchorInput) -> str:
        """管理大纲锚点配额，包括初始化、推进、注入约束和检查。"""
        try:
            args = [params.action, params.book_dir]
            if params.chapter:
                args.extend(["--chapter", str(params.chapter)])
            if params.quota:
                args.extend(["--quota", params.quota])
            
            result = outline_anchor_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 事件矩阵工具 ============
    
    @mcp.tool(
        name="novel_event_matrix",
        annotations={
            "title": "事件矩阵管理",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def novel_event_matrix(params: EventMatrixInput) -> str:
        """管理5+1类事件，包括推荐、记录和查询冷却状态。"""
        try:
            args = [params.action, params.book_dir]
            if params.event_type:
                args.extend(["--event-type", params.event_type])
            if params.chapter:
                args.extend(["--chapter", str(params.chapter)])
            
            result = event_matrix_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 实体索引工具 ============
    
    @mcp.tool(
        name="novel_entity_index",
        annotations={
            "title": "实体索引管理",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def novel_entity_index(params: EntityIndexInput) -> str:
        """构建实体索引或执行语义检索。"""
        try:
            args = [params.action, params.book_dir]
            if params.query:
                args.extend(["--query", params.query])
            
            result = entity_index_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 知识图谱工具 ============
    
    @mcp.tool(
        name="novel_story_graph",
        annotations={
            "title": "知识图谱管理",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def novel_story_graph(params: StoryGraphInput) -> str:
        """管理故事知识图谱，包括构建、查询、级联标记和影响分析。"""
        try:
            args = [params.action, params.book_dir]
            if params.node:
                args.extend(["--node", params.node])
            
            result = story_graph_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 调研工具 ============
    
    @mcp.tool(
        name="novel_research",
        annotations={
            "title": "联网调研",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True
        }
    )
    async def novel_research(params: ResearchInput) -> str:
        """执行联网调研，包括制定计划、识别缺口和存储结果。"""
        try:
            args = [params.action]
            if params.book_dir:
                args.extend([params.book_dir])
            if params.chapter_goal:
                args.extend(["--chapter-goal", params.chapter_goal])
            if params.genre:
                args.extend(["--genre", params.genre])
            if params.topic:
                args.extend(["--topic", params.topic])
            
            result = research_agent_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 风格库工具 ============
    
    @mcp.tool(
        name="novel_style_library",
        annotations={
            "title": "风格库管理",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def novel_style_library(params: StyleLibraryInput) -> str:
        """跨书风格库管理，包括导入、搜索、应用和删除风格。"""
        try:
            args = [params.action]
            if params.source_dir:
                args.extend(["--source", params.source_dir])
            if params.tags:
                args.extend(["--tags", params.tags])
            if params.style_id:
                args.extend(["--style-id", params.style_id])
            
            result = style_library_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 内容扩充工具 ============
    
    @mcp.tool(
        name="novel_content_expander",
        annotations={
            "title": "智能内容扩充",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def novel_content_expander(params: ContentExpanderInput) -> str:
        """智能内容扩充，分析章节并提供五维扩充建议。"""
        try:
            args = [params.book_dir, "--chapter", str(params.chapter)]
            if params.target_chars:
                args.extend(["--target-chars", str(params.target_chars)])
            
            result = content_expander_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 上下文管理工具 ============
    
    @mcp.tool(
        name="novel_context_manager",
        annotations={
            "title": "上下文管理",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def novel_context_manager(params: ContextManagerInput) -> str:
        """最小上下文选取和压缩，解决百万字上下文爆炸问题。"""
        try:
            args = [params.action, str(params.chapter), "--book-dir", params.book_dir]
            
            result = context_manager_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 流程编排工具 ============
    
    @mcp.tool(
        name="novel_flow",
        annotations={
            "title": "小说流程编排",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def novel_flow(params: NovelFlowInput) -> str:
        """统一流程执行，包括状态检查、准备、写作、日更、修订和报告。"""
        try:
            args = [params.action, params.book_dir]
            if params.chapters:
                args.extend(["--chapters", str(params.chapters)])
            
            result = novel_flow_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 质量评分工具 ============
    
    @mcp.tool(
        name="novel_quality_score",
        annotations={
            "title": "质量评分",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def novel_quality_score(params: QualityScoreInput) -> str:
        """七维加权质量评分，包括AI腔、节奏、文风、情感、结构、对话、可读性。"""
        try:
            args = [params.action, params.chapter_file, "--chapter", str(params.chapter), "--book-dir", params.book_dir]
            
            result = quality_score_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ Beat Sheet工具 ============
    
    @mcp.tool(
        name="novel_beat_sheet",
        annotations={
            "title": "Beat Sheet生成",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def novel_beat_sheet(params: BeatSheetInput) -> str:
        """Beat Sheet多步流水线，包括分镜生成、扩写和合成校验。"""
        try:
            args = [params.action, params.book_dir, "--chapter", str(params.chapter)]
            
            result = beat_sheet_generator_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 章节合成工具 ============
    
    @mcp.tool(
        name="novel_chapter_synthesizer",
        annotations={
            "title": "章节合成",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def novel_chapter_synthesizer(params: ChapterSynthesizerInput) -> str:
        """章节合成器，Beat拼接+过渡检测+质量校验+润色提示。"""
        try:
            args = [params.book_dir, "--chapter", str(params.chapter)]
            
            result = chapter_synthesizer_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 门禁修复工具 ============
    
    @mcp.tool(
        name="novel_gate_repair",
        annotations={
            "title": "门禁修复",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def novel_gate_repair(params: GateRepairInput) -> str:
        """门禁修复计划，分析失败原因并生成最短修复路径。"""
        try:
            args = [params.book_dir, "--chapter", str(params.chapter)]
            
            result = gate_repair_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 编辑团队工具 ============
    
    @mcp.tool(
        name="novel_editorial_manager",
        annotations={
            "title": "编辑团队管理",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def novel_editorial_manager(params: EditorialManagerInput) -> str:
        """编辑团队状态管理，包括快照、状态查询和人工介入检测。"""
        try:
            args = [params.action, params.book_dir]
            if params.chapter:
                args.extend(["--chapter", str(params.chapter)])
            
            result = editorial_manager_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ Hook工具 ============
    
    @mcp.tool(
        name="novel_hooks",
        annotations={
            "title": "自动化Hook",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def novel_hooks(params: HooksInput) -> str:
        """自动化Hook机制，包括会话开始、大纲守卫、正文扫描、缺口检测、压缩前快照。"""
        try:
            args = [params.action, params.book_dir]
            if params.chapter:
                args.extend(["--chapter", str(params.chapter)])
            if params.file:
                args.extend(["--file", params.file])
            
            result = hooks_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ RAG检索工具 ============
    
    @mcp.tool(
        name="novel_rag_retriever",
        annotations={
            "title": "RAG检索增强",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def novel_rag_retriever(params: RAGRetrieverInput) -> str:
        """BM25两级语义检索，包括增量索引、查询缓存和命中可解释。"""
        try:
            args = [params.action, params.book_dir]
            if params.query:
                args.extend(["--query", params.query])
            args.extend(["--top", str(params.top)])
            
            result = rag_retriever_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 书籍初始化工具 ============
    
    @mcp.tool(
        name="novel_init_book",
        annotations={
            "title": "初始化书籍工程",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def novel_init_book(params: InitBookInput) -> str:
        """一键初始化书籍工程，创建目录骨架和追踪文件。"""
        try:
            args = [params.title, "--genre", params.genre, "--platform", params.platform]
            
            result = init_book_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 会话恢复工具 ============
    
    @mcp.tool(
        name="novel_resume",
        annotations={
            "title": "会话恢复",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def novel_resume(params: ResumeInput) -> str:
        """恢复写作会话，检查欠账和追踪文件状态。"""
        try:
            args = [params.book_dir]
            
            result = resume_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 标点归一化工具 ============
    
    @mcp.tool(
        name="novel_normalize_punct",
        annotations={
            "title": "标点归一化",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def novel_normalize_punct(params: NormalizePunctInput) -> str:
        """标点符号归一化，清理非功能性标点堆叠。"""
        try:
            args = [params.file_path]
            if params.check:
                args.append("--check")
            
            result = normalize_punct_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    # ============ 追踪验证工具 ============
    
    @mcp.tool(
        name="novel_validate_tracking",
        annotations={
            "title": "追踪文件验证",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def novel_validate_tracking(params: ValidateTrackingInput) -> str:
        """验证追踪文件格式，防止模型写歪。"""
        try:
            args = [params.book_dir]
            
            result = validate_tracking_main(args)
            return json.dumps({"success": True, "exit_code": result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    return mcp


def main():
    """主入口"""
    if not HAS_MCP:
        print("错误: MCP SDK未安装", file=sys.stderr)
        print("请安装: pip install mcp", file=sys.stderr)
        print("\n或使用 stdio 模式运行:", file=sys.stderr)
        print("  python server.py", file=sys.stderr)
        sys.exit(1)
    
    import argparse
    parser = argparse.ArgumentParser(description="long-novel-skill MCP Server")
    parser.add_argument("--http", action="store_true", help="使用HTTP模式（默认stdio）")
    parser.add_argument("--port", type=int, default=8000, help="HTTP端口（默认8000）")
    args = parser.parse_args()
    
    mcp = create_mcp_server()
    
    if args.http:
        print(f"启动HTTP服务器，端口 {args.port}...")
        mcp.run(transport="streamable_http", port=args.port)
    else:
        print("启动stdio服务器...")
        mcp.run()


if __name__ == "__main__":
    main()
