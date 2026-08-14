# long-novel-skill 跨平台安装脚本 (PowerShell)
# 支持: Claude Code, TRAE, Cursor, Codex, OpenCode, Gemini CLI, Antigravity

param(
    [string]$Tool = "",
    [switch]$Force,
    [switch]$Help
)

$SkillName = "long-novel-skill"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 颜色函数
function Write-Info { param($Message) Write-Host "[INFO] $Message" -ForegroundColor Green }
function Write-Warn { param($Message) Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-Error2 { param($Message) Write-Host "[ERROR] $Message" -ForegroundColor Red }

function Show-Help {
    @"
用法: .\install.ps1 [选项]

选项:
    -Tool <工具名>    指定目标工具 (claude-code|trae|cursor|codex|opencode|gemini-cli|antigravity|all)
    -Force            强制覆盖已有skill
    -Help             显示此帮助

示例:
    .\install.ps1 -Tool claude-code          # 安装到Claude Code
    .\install.ps1 -Tool trae                 # 安装到TRAE
    .\install.ps1 -Tool all -Force           # 安装到所有平台（强制覆盖）
"@
}

function Get-SkillDir {
    param([string]$Tool)
    $homeDir = $env:USERPROFILE
    switch ($Tool) {
        "claude-code" { return "$homeDir\.claude\skills" }
        "trae" {
            if (Test-Path "$homeDir\.trae\skills") {
                return "$homeDir\.trae\skills"
            } elseif (Test-Path ".trae\skills") {
                return "$PWD\.trae\skills"
            } else {
                return "$homeDir\.trae\skills"
            }
        }
        "cursor" { return "$homeDir\.cursor\skills" }
        "codex" { return "$homeDir\.codex\skills" }
        "opencode" { return "$homeDir\.opencode\skills" }
        "gemini-cli" { return "$homeDir\.gemini\skills" }
        "antigravity" { return "$homeDir\.antigravity\skills" }
        default {
            Write-Error2 "未知工具: $Tool"
            exit 1
        }
    }
}

function Install-Skill {
    param([string]$Tool)
    $skillDir = Get-SkillDir -Tool $Tool
    $target = Join-Path $skillDir $SkillName

    Write-Info "安装到 $Tool`: $target"

    # 创建目录
    New-Item -ItemType Directory -Force -Path $skillDir | Out-Null

    # 检查是否已存在
    if (Test-Path $target) {
        if (-not $Force) {
            Write-Warn "$Tool 中已存在 $SkillName，使用 -Force 覆盖"
            return $false
        }
        Remove-Item -Recurse -Force $target
    }

    # 复制skill文件（排除不需要的文件；mcp_server 一并复制，MCP 需另行 pip install mcp）
    $exclude = @('__pycache__', '*.pyc', '.git')
    Copy-Item -Recurse -Path $ScriptDir -Destination $target -Force

    # 清理排除文件
    foreach ($pattern in $exclude) {
        Get-ChildItem -Recurse -Path $target -Filter $pattern | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Info "✓ 成功安装到 $Tool"
    return $true
}

function Detect-InstalledTools {
    $tools = @()
    $homeDir = $env:USERPROFILE
    if (Test-Path "$homeDir\.claude") { $tools += "claude-code" }
    if (Test-Path "$homeDir\.trae" -or (Test-Path ".trae")) { $tools += "trae" }
    if (Test-Path "$homeDir\.cursor") { $tools += "cursor" }
    if (Test-Path "$homeDir\.codex") { $tools += "codex" }
    if (Test-Path "$homeDir\.opencode") { $tools += "opencode" }
    if (Test-Path "$homeDir\.gemini") { $tools += "gemini-cli" }
    if (Test-Path "$homeDir\.antigravity") { $tools += "antigravity" }
    return $tools
}

# 主逻辑
if ($Help) {
    Show-Help
    exit 0
}

if ([string]::IsNullOrEmpty($Tool)) {
    Write-Error2 "请指定目标工具，使用 -Tool <工具名>"
    Write-Host ""
    Write-Info "已检测到的工具:"
    $detected = Detect-InstalledTools
    if ($detected.Count -gt 0) {
        foreach ($t in $detected) {
            Write-Host "  - $t"
        }
        Write-Host ""
        Write-Info "使用示例: .\install.ps1 -Tool $($detected[0])"
    } else {
        Write-Host "  (未检测到任何工具)"
        Write-Host ""
        Write-Info "可用工具: claude-code, trae, cursor, codex, opencode, gemini-cli, antigravity, all"
    }
    exit 1
}

if ($Tool -eq "all") {
    $detected = Detect-InstalledTools
    if ($detected.Count -eq 0) {
        Write-Warn "未检测到任何工具，将安装到所有可能的目录"
        $detected = @("claude-code", "trae", "cursor", "codex", "opencode", "gemini-cli", "antigravity")
    }

    $success = 0
    $failed = 0
    foreach ($t in $detected) {
        if (Install-Skill -Tool $t) {
            $success++
        } else {
            $failed++
        }
    }

    Write-Host ""
    Write-Info "安装完成: $success 成功, $failed 跳过/失败"
} else {
    Install-Skill -Tool $Tool | Out-Null
}

Write-Host ""
Write-Info "安装完成！"
Write-Info "提示: 安装后可能需要重启AI客户端或新开会话才能生效"
Write-Info "机械 Hook（可选）: 在书籍工程目录内运行 python scripts/deploy_hooks.py <书名目录> 以启用无纲写正文/毒句式欠账的机械阻断"
