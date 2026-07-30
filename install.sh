#!/usr/bin/env bash
# long-novel-skill 跨平台安装脚本
# 支持: Claude Code, TRAE, Cursor, Codex, OpenCode, Gemini CLI, Antigravity

set -euo pipefail

SKILL_NAME="long-novel-skill"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FORCE=false

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    cat <<EOF
用法: $0 [选项]

选项:
    -t, --tool <工具名>    指定目标工具 (claude-code|trae|cursor|codex|opencode|gemini-cli|antigravity|all)
    -f, --force            强制覆盖已有skill
    -h, --help             显示此帮助

示例:
    $0 --tool claude-code          # 安装到Claude Code
    $0 --tool trae                 # 安装到TRAE
    $0 --tool all --force          # 安装到所有平台（强制覆盖）
EOF
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检测平台
get_skill_dir() {
    local tool=$1
    case "$tool" in
        claude-code)
            echo "$HOME/.claude/skills"
            ;;
        trae)
            # TRAE支持全局和项目级skills
            if [ -d "$HOME/.trae/skills" ]; then
                echo "$HOME/.trae/skills"
            elif [ -d ".trae/skills" ]; then
                echo "$PWD/.trae/skills"
            else
                echo "$HOME/.trae/skills"
            fi
            ;;
        cursor)
            echo "$HOME/.cursor/skills"
            ;;
        codex)
            echo "$HOME/.codex/skills"
            ;;
        opencode)
            echo "$HOME/.opencode/skills"
            ;;
        gemini-cli)
            echo "$HOME/.gemini/skills"
            ;;
        antigravity)
            echo "$HOME/.antigravity/skills"
            ;;
        *)
            log_error "未知工具: $tool"
            exit 1
            ;;
    esac
}

# 安装skill到指定目录
install_skill() {
    local tool=$1
    local skill_dir=$(get_skill_dir "$tool")
    local target="$skill_dir/$SKILL_NAME"

    log_info "安装到 $tool: $target"

    # 创建目录
    mkdir -p "$skill_dir"

    # 检查是否已存在
    if [ -d "$target" ] && [ "$FORCE" != true ]; then
        log_warn "$tool 中已存在 $SKILL_NAME，使用 --force 覆盖"
        return 1
    fi

    # 复制skill文件
    # 排除不需要的文件
    rsync -av --exclude='__pycache__' \
              --exclude='*.pyc' \
              --exclude='.git' \
              --exclude='mcp_server' \
              "$SCRIPT_DIR/" "$target/" 2>/dev/null || \
    cp -R "$SCRIPT_DIR" "$target"

    # 创建 .trae/agents 目录（如果工具是trae且存在agents）
    if [ "$tool" = "trae" ] && [ -d "$SCRIPT_DIR/assets/agents" ]; then
        local agents_dir="$target/assets/agents"
        if [ -d "$agents_dir" ]; then
            log_info "已复制agents定义到 $agents_dir"
        fi
    fi

    log_info "✓ 成功安装到 $tool"
    return 0
}

# 检测已安装的工具
detect_installed_tools() {
    local tools=()
    [ -d "$HOME/.claude" ] && tools+=("claude-code")
    [ -d "$HOME/.trae" ] || [ -d ".trae" ] && tools+=("trae")
    [ -d "$HOME/.cursor" ] && tools+=("cursor")
    [ -d "$HOME/.codex" ] && tools+=("codex")
    [ -d "$HOME/.opencode" ] && tools+=("opencode")
    [ -d "$HOME/.gemini" ] && tools+=("gemini-cli")
    [ -d "$HOME/.antigravity" ] && tools+=("antigravity")
    echo "${tools[@]}"
}

# 主函数
main() {
    local TOOL=""

    # 解析参数
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -t|--tool)
                TOOL="$2"
                shift 2
                ;;
            -f|--force)
                FORCE=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "未知选项: $1"
                usage
                exit 1
                ;;
        esac
    done

    # 验证参数
    if [ -z "$TOOL" ]; then
        log_error "请指定目标工具，使用 --tool <工具名>"
        echo ""
        log_info "已检测到的工具:"
        detected=$(detect_installed_tools)
        if [ -n "$detected" ]; then
            for t in $detected; do
                echo "  - $t"
            done
            echo ""
            log_info "使用示例: $0 --tool $(echo $detected | awk '{print $1}')"
        else
            echo "  (未检测到任何工具)"
            echo ""
            log_info "可用工具: claude-code, trae, cursor, codex, opencode, gemini-cli, antigravity, all"
        fi
        exit 1
    fi

    # 执行安装
    if [ "$TOOL" = "all" ]; then
        local detected=$(detect_installed_tools)
        if [ -z "$detected" ]; then
            log_warn "未检测到任何工具，将安装到所有可能的目录"
            detected="claude-code trae cursor codex opencode gemini-cli antigravity"
        fi

        local success=0
        local failed=0
        for t in $detected; do
            if install_skill "$t"; then
                ((success++))
            else
                ((failed++))
            fi
        done

        echo ""
        log_info "安装完成: $success 成功, $failed 跳过/失败"
    else
        install_skill "$TOOL"
    fi

    echo ""
    log_info "安装完成！"
    log_info "提示: 安装后可能需要重启AI客户端或新开会话才能生效"
}

main "$@"
