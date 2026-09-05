#!/usr/bin/env python3
"""Deterministic contract checks for a repository SKILL.md file."""

import ast
import argparse
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


ALLOWED_FRONTMATTER = {"name", "description", "license", "metadata", "allowed-tools"}
CRITICAL_ROUTES = {
    "references/workflow/" + name + ".md" for name in (
        "task-router", "book-init", "outline-system", "chapter-loop", "daily-failfast",
        "revision", "import-book", "cross-review", "short-story-loop", "publishing-pack",
        "dashboard-workbench")
} | {"references/craft/scene-rendering.md"}


@dataclass
class AuditReport:
    errors: List[str]
    warnings: List[str]


def _frontmatter_bounds(lines: List[str]) -> Optional[Tuple[int, int]]:
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return 0, index
    return None


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def extract_frontmatter(text: str) -> Dict[str, Any]:
    """Extract the small YAML subset needed by the skill contract.

    Only unindented ``key: value`` lines become top-level entries.  This keeps
    nested ``metadata`` keys from being confused with unsupported fields.
    """
    lines = text.splitlines()
    bounds = _frontmatter_bounds(lines)
    if bounds is None:
        return {}

    frontmatter = {}
    active_block = None
    active_metadata = False
    for line in lines[bounds[0] + 1:bounds[1]]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        top_level = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):(?:[ \t]*(.*))?$", line)
        if top_level:
            key, raw_value = top_level.groups()
            raw_value = raw_value or ""
            active_block = key if raw_value.strip() in ("|", ">", "|-", ">-") else None
            active_metadata = key == "metadata" and not raw_value.strip()
            if active_metadata:
                frontmatter[key] = {}
            elif active_block is not None:
                frontmatter[key] = ""
            else:
                frontmatter[key] = _scalar(raw_value)
            continue

        if active_block is not None and line[:1].isspace():
            value = line.strip()
            if value:
                existing = frontmatter[active_block]
                frontmatter[active_block] = (existing + " " + value).strip()
            continue

        if active_metadata and line[:1].isspace():
            nested = re.match(r"^[ \t]+([A-Za-z][A-Za-z0-9_-]*):(?:[ \t]*(.*))?$", line)
            if nested:
                key, raw_value = nested.groups()
                frontmatter["metadata"][key] = _scalar(raw_value or "")
            continue

        active_block = None
        active_metadata = False

    return frontmatter


def referenced_local_paths(text: str) -> Set[str]:
    """Return explicit local paths mentioned inside backticked text."""
    paths = set()
    candidate_pattern = re.compile(
        r"(?<![A-Za-z0-9_.:/-])((?:references|scripts|assets)/[^\s`<>\"']+)"
    )
    python_command = re.compile(
        r"^(?:python(?:\d+(?:\.\d+)*)?|py)\s+([^\s`]+)"
    )
    for match in re.finditer(r"`([^`\n]+)`", text):
        snippet = match.group(1).strip()
        command = python_command.match(snippet)
        if command:
            candidate = command.group(1)
            for path in _local_path_candidates(candidate_pattern, candidate):
                paths.add(path)
            continue
        if "://" in snippet:
            continue
        for candidate in candidate_pattern.findall(snippet):
            for path in _local_path_candidates(candidate_pattern, candidate):
                paths.add(path)
    return paths


def _local_path_candidates(pattern: re.Pattern, value: str) -> Set[str]:
    """Normalize a matched path and reject parameterized placeholders."""
    paths = set()
    for candidate in pattern.findall(value):
        path = candidate.rstrip(".,:;!?)]}")
        if path and "$" not in path and "{" not in path:
            paths.add(path)
    return paths


def _body_lines(text: str) -> List[str]:
    lines = text.splitlines()
    bounds = _frontmatter_bounds(lines)
    if bounds is None:
        return lines
    return lines[bounds[1] + 1:]


def _logical_skill_folder(root: Path) -> str:
    """Return the source repository name for a linked Git worktree.

    A normal checkout has a ``.git`` directory and remains strictly bound to
    its folder name.  A linked worktree has a ``.git`` text file whose gitdir
    lives below ``<source>/.git/worktrees/<worktree>``; in that one case the
    source folder is the logical skill folder.
    """
    dot_git = root / ".git"
    if not dot_git.is_file():
        return root.name
    try:
        marker = dot_git.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return root.name
    if not marker.lower().startswith("gitdir:"):
        return root.name
    gitdir_text = marker.split(":", 1)[1].strip()
    gitdir = Path(gitdir_text)
    if not gitdir.is_absolute():
        gitdir = (root / gitdir).resolve()
    parts = gitdir.parts
    lowered = [part.lower() for part in parts]
    try:
        worktrees_index = lowered.index("worktrees")
    except ValueError:
        return root.name
    if worktrees_index < 2 or lowered[worktrees_index - 1] != ".git":
        return root.name
    return parts[worktrees_index - 2]


def _commands(text):
    """Only shell examples beginning with a Python executable; never execute them."""
    text = re.sub(r"\\\s*\n", " ", text)
    snippets = re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.S))
    snippets.extend(line.strip() for language, block in re.findall(r"```([^\n]*)\n(.*?)```", text, re.S)
                    if language.strip().lower() in ("", "bash", "sh", "shell", "console", "powershell", "cmd", "zsh")
                    for line in block.splitlines())
    for snippet in snippets:
        if not re.match(r"^(?:python(?:\d+(?:\.\d+)*)?|py)\s+", snippet):
            continue
        try:
            tokens = shlex.split(snippet, comments=True)
        except ValueError:
            continue
        if len(tokens) > 1 and tokens[1].endswith(".py"):
            yield tokens[1], tokens[2:]


def _resolve_reference(root, document, value, markdown=False):
    value = value.strip().split("#", 1)[0].rstrip(".,;:!?)]}")
    if not value or "://" in value or any(c in value for c in "{}$<>*|\n "):
        return None
    if value.startswith("/") or "\\" in value:
        return None
    explicit = value.startswith(("references/", "scripts/", "assets/", "evals/", "evaluations/", "mcp_server/"))
    if not explicit and not markdown and not re.match(r"[A-Za-z_.][A-Za-z0-9_./-]*\.(?:md|py|json)$", value):
        return None
    if explicit:
        candidate = root / value
    elif value.startswith(("craft/", "workflow/", "genres/", "platforms/")):
        candidate = root / "references" / value
    elif value.startswith("templates/"):
        candidate = root / "assets" / value
    else:
        candidate = document.parent / value
        # Legacy references use unique basenames across reference categories.
        # Existing files only; a typo still resolves to a missing relative path.
        if "/" not in value and not candidate.exists():
            # A legacy run log may name an artifact in its own blind bundle.
            # A later run with the same basename must not break that local link.
            # Multiple local candidates stay ambiguous; never choose the first.
            matches = [
                match for match in document.parent.rglob(value)
                if match.relative_to(root).parts[:1] not in ((".git",), (".worktrees",))
            ]
            if not matches:
                matches = (list((root / "references").rglob(value)) + list((root / "scripts").rglob(value))
                           + list((root / "assets").rglob(value)) + list((root / "mcp_server").glob(value))
                           + list((root / "evaluations").rglob(value)))
            if len(matches) == 1:
                candidate = matches[0]
    try:
        return candidate.resolve().relative_to(root).as_posix()
    except ValueError:
        return "!outside:" + value


def _document_references(root, document, text):
    references = set()
    # Remove fences before scanning inline code; examples' output arguments are
    # runtime project paths, not resources of the skill.
    inline_text = re.sub(r"```.*?```", "", text, flags=re.S)
    for snippet in re.findall(r"`([^`\n]+)`", inline_text):
        if re.match(r"^(?:python[\d.]*|py)\s", snippet):
            continue
        relative = _resolve_reference(root, document, snippet)
        if relative:
            references.add(relative)
    for value in re.findall(r"\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", inline_text):
        relative = _resolve_reference(root, document, value, markdown=True)
        if relative:
            references.add(relative)
    for script, _ in _commands(text):
        relative = _resolve_reference(root, document, script)
        if relative:
            references.add(relative)
    return references


def _literal(node, default=None):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return default


class _CommandSyntaxError(ValueError):
    pass


class _ContractParser(argparse.ArgumentParser):
    def error(self, message):
        raise _CommandSyntaxError(message)


def _cli_contract(script):
    """Reconstruct ONLY literal argparse declarations, never import the script.

    Standard argparse then checks syntax (required/positional/nargs/abbreviation).
    Type converters, callbacks, defaults and non-command choices are not run:
    project placeholders remain valid values, not filesystem or numeric inputs.
    Literal declaration loops and simple loop-name comparisons are supported.
    This is a declaration extractor, not a Python evaluator or runtime checker.
    """
    tree = ast.parse(script.read_text(encoding="utf-8-sig"))
    constructors = {"ArgumentParser"}
    constructors.update(node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
                        and any(getattr(base, "attr", getattr(base, "id", "")) == "ArgumentParser"
                                for base in node.bases))
    roots = []
    unknown = object()
    active_helpers = set()

    def value(node, names):
        return names.get(node.id, unknown) if isinstance(node, ast.Name) else _literal(node, unknown)

    def declaration(call, names):
        if not isinstance(call, ast.Call):
            return unknown
        function = call.func
        method = getattr(function, "attr", getattr(function, "id", ""))
        kwargs = {kw.arg: value(kw.value, names) for kw in call.keywords}
        kwargs = {key: val for key, val in kwargs.items() if val is not unknown}
        helper = names.get(method)
        arguments = [value(arg, names) for arg in call.args]
        if (isinstance(helper, ast.FunctionDef) and method not in active_helpers
                and any(isinstance(arg, _ContractParser) for arg in arguments)):
            bindings = dict(names)
            parameters = helper.args.args
            for parameter, default in zip(parameters[len(parameters) - len(helper.args.defaults):], helper.args.defaults):
                bindings[parameter.arg] = value(default, names)
            bindings.update({parameter.arg: arg for parameter, arg in zip(parameters, arguments)})
            bindings.update(kwargs)
            active_helpers.add(method)
            try:
                visit(helper.body, bindings)
            finally:
                active_helpers.remove(method)
            return unknown
        if method in constructors:
            parser = _ContractParser(**{key: kwargs[key] for key in ("allow_abbrev", "add_help") if key in kwargs})
            roots.append(parser)
            return parser
        owner = names.get(getattr(getattr(function, "value", None), "id", ""))
        if method == "add_subparsers" and isinstance(owner, _ContractParser):
            return owner.add_subparsers(**{key: kwargs[key] for key in ("dest", "required") if key in kwargs})
        if method == "add_parser" and isinstance(owner, argparse._SubParsersAction):
            name = value(call.args[0], names) if call.args else unknown
            if isinstance(name, str):
                return owner.add_parser(name, **{key: kwargs[key] for key in ("allow_abbrev", "add_help", "aliases") if key in kwargs})
        if method == "add_argument" and isinstance(owner, _ContractParser):
            args = [value(arg, names) for arg in call.args]
            if not args or not all(isinstance(arg, str) for arg in args):
                return unknown
            accepted = {key: kwargs[key] for key in ("required", "nargs", "dest", "const") if key in kwargs}
            action = kwargs.get("action")
            if action in ("store_true", "store_false", "store_const", "append", "append_const", "count"):
                accepted["action"] = action
            if args[0] in ("mode", "command", "cmd", "action") and isinstance(kwargs.get("choices"), (list, tuple)):
                accepted["choices"] = kwargs["choices"]
            return owner.add_argument(*args, **accepted)
        return unknown

    def visit(statements, names):
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names[node.name] = node
                visit(node.body, dict(names))
            elif isinstance(node, ast.Assign):
                result = declaration(node.value, names) if isinstance(node.value, ast.Call) else value(node.value, names)
                if result is not unknown:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            names[target.id] = result
            elif isinstance(node, ast.Expr):
                declaration(node.value, names)
            elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                sequence = value(node.iter, names)
                if isinstance(sequence, (list, tuple)):
                    for item in sequence:
                        visit(node.body, dict(names, **{node.target.id: item}))
            elif isinstance(node, ast.If):
                test = node.test
                if isinstance(value(test, names), bool):
                    visit(node.body if value(test, names) else node.orelse, names)
                elif (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
                        and value(test.left, names) is not unknown and value(test.comparators[0], names) is not unknown):
                    branch = node.body if value(test.left, names) == value(test.comparators[0], names) else node.orelse
                    visit(branch, names)
                else:
                    visit(node.body, names)
                    visit(node.orelse, names)

    visit(tree.body, {})
    return roots[0] if roots else None


def _audit_command(root, document, script, arguments):
    relative = _resolve_reference(root, document, script)
    if not relative or relative.startswith("!") or not (root / relative).is_file():
        return []
    try:
        parser = _cli_contract(root / relative)
    except (OSError, SyntaxError, UnicodeError, argparse.ArgumentError, TypeError, ValueError) as exc:
        return ["invalid_cli_contract:" + relative + ":" + type(exc).__name__]
    if parser is None:
        return []  # Non-argparse entrypoints have no statically declared syntax.
    arguments = list(arguments)
    for index, argument in enumerate(arguments):
        if argument in ("|", ">", ">>", "&&", ";"):
            arguments = arguments[:index]
            break
    if "--help" in arguments or "-h" in arguments:
        return []
    try:
        parser.parse_args(arguments)
    except _CommandSyntaxError as exc:
        message = str(exc)
        if "required:" in message:
            return ["missing_required:" + relative + ":" + message.split("required:", 1)[1].strip()]
        if message.startswith("argument ") and ": expected " in message:
            return ["missing_value:" + relative + ":" + message.split(":", 1)[0][9:]]
        if "invalid choice:" in message:
            choice = re.search(r"invalid choice: '([^']*)'", message)
            return ["unknown_subcommand:" + relative + ":" + (choice.group(1) if choice else message)]
        if message.startswith("unrecognized arguments:"):
            flags = re.findall(r"(?<!\S)--?[A-Za-z][A-Za-z0-9-]*", message)
            return ["unknown_flag:" + relative + ":" + flag for flag in flags] or ["invalid_arguments:" + relative + ":" + message]
        return ["invalid_arguments:" + relative + ":" + message]
    return []


def _audit_reachable(root):
    seen, errors, pending = set(), [], ["SKILL.md"]
    if (root / "README.md").is_file():
        pending.append("README.md")
    while pending:
        relative = pending.pop()
        if relative in seen:
            continue
        seen.add(relative)
        document = root / relative
        try:
            text = document.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append("unreadable_document:" + relative)
            continue
        for link in sorted(_document_references(root, document, text)):
            if link.startswith("!"):
                errors.append("outside_reference:" + link[9:])
            elif not (root / link).exists():
                errors.append("missing_path:" + link)
            elif link.endswith(".md"):
                pending.append(link)
        for script, arguments in _commands(text):
            errors.extend(_audit_command(root, document, script, arguments))
    for route in sorted(CRITICAL_ROUTES):
        if (root / route).exists() and route not in seen:
            errors.append("unreachable_route:" + route)
    return sorted(set(errors))


def audit_skill(root: Path) -> AuditReport:
    """Audit one skill directory without relying on a YAML parser."""
    root = Path(root).resolve()
    skill_file = root / "SKILL.md"
    errors = []
    warnings = []
    if not skill_file.is_file():
        return AuditReport(errors=["missing_skill:SKILL.md"], warnings=[])

    text = skill_file.read_text(encoding="utf-8")
    frontmatter = extract_frontmatter(text)
    for key in sorted(frontmatter):
        if key not in ALLOWED_FRONTMATTER:
            errors.append("unsupported_frontmatter:" + key)

    name = frontmatter.get("name")
    logical_folder = _logical_skill_folder(root)
    if name != logical_folder:
        errors.append("name_mismatch:" + logical_folder)

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.startswith("Use when"):
        errors.append("invalid_description")

    errors.extend(_audit_reachable(root))

    body_line_count = len(_body_lines(text))
    if body_line_count > 250:
        warnings.append("body_too_long:" + str(body_line_count))

    return AuditReport(errors=sorted(errors), warnings=sorted(warnings))


def main(argv: Optional[List[str]] = None) -> int:
    """Run the skill audit for an optional root directory."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = Path(arguments[0]) if arguments else Path(".")
    report = audit_skill(root)
    for error in report.errors:
        print("ERROR " + error)
    for warning in report.warnings:
        print("WARNING " + warning)
    if report.errors:
        print("FAIL")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
