"""Краткое описание публичного API + сигнатуры для валидатора (AST, без NXOpen)."""
from __future__ import annotations

import ast
from pathlib import Path

from .config import LIBRARY_DIR


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _format_args(args: ast.arguments) -> str:
    parts = []
    defaults = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults)

    for arg, default in zip(args.args, defaults):
        piece = arg.arg
        if arg.annotation is not None:
            try:
                piece += f": {ast.unparse(arg.annotation)}"
            except Exception:
                pass
        if default is not None:
            try:
                piece += f"={ast.unparse(default)}"
            except Exception:
                piece += "=..."
        parts.append(piece)

    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    for kwarg, default in zip(args.kwonlyargs, args.kw_defaults):
        piece = kwarg.arg
        if default is not None:
            try:
                piece += f"={ast.unparse(default)}"
            except Exception:
                piece += "=..."
        parts.append(piece)

    return "(" + ", ".join(parts) + ")"


def _first_doc_line(node) -> str | None:
    doc = ast.get_docstring(node)
    if not doc:
        return None
    return doc.strip().splitlines()[0]


def _public_names() -> set[str]:
    init_source = read_text(LIBRARY_DIR / "__init__.py")
    init_tree = ast.parse(init_source)
    public_names: set[str] = set()
    for node in ast.walk(init_tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant):
                    public_names.add(elt.value)
    return public_names


def build_library_description() -> str:
    public_names = _public_names()
    parts = [
        "=" * 80,
        "PUBLIC API (сигнатуры + краткие описания, без реализации)",
        "Используй ТОЛЬКО то, что здесь перечислено.",
        "=" * 80,
        "",
    ]

    for file in sorted(LIBRARY_DIR.rglob("*.py")):
        if file.name == "__init__.py":
            continue
        tree = ast.parse(read_text(file))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    node.col_offset == 0 and node.name in public_names:
                parts.append(f"def {node.name}{_format_args(node.args)}")
                doc = _first_doc_line(node)
                if doc:
                    parts.append(f"    # {doc}")
                parts.append("")
            elif isinstance(node, ast.ClassDef) and node.name in public_names:
                parts.append(f"class {node.name}:")
                doc = _first_doc_line(node)
                if doc:
                    parts.append(f"    # {doc}")
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name.startswith("_") and item.name != "__init__":
                            continue
                        prefix = "def __init__" if item.name == "__init__" else f"def {item.name}"
                        parts.append(f"    {prefix}{_format_args(item.args)}")
                        item_doc = _first_doc_line(item)
                        if item_doc:
                            parts.append(f"        # {item_doc}")
                parts.append("")

    parts.append("=" * 80)
    parts.append("END OF API")
    parts.append("=" * 80)
    return "\n".join(parts)


def _extract_param_names(args: ast.arguments) -> set[str]:
    names: set[str] = set()
    for a in args.args:
        names.add(a.arg)
    for a in args.kwonlyargs:
        names.add(a.arg)
    if args.vararg:
        names.add("*")
    if args.kwarg:
        names.add("**")
    return names


def build_api_signatures() -> dict[str, set[str]]:
    public_names = _public_names()
    signatures: dict[str, set[str]] = {}

    for file in sorted(LIBRARY_DIR.rglob("*.py")):
        if file.name == "__init__.py":
            continue
        tree = ast.parse(read_text(file))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    node.col_offset == 0 and node.name in public_names:
                signatures[node.name] = _extract_param_names(node.args)
            elif isinstance(node, ast.ClassDef) and node.name in public_names:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name.startswith("_") and item.name != "__init__":
                            continue
                        params = _extract_param_names(item.args)
                        params.discard("self")
                        key = node.name if item.name == "__init__" else item.name
                        if key in signatures:
                            signatures[key] |= params
                        else:
                            signatures[key] = params
    return signatures


_API_SIGNATURES_CACHE: dict[str, set[str]] | None = None


def get_api_signatures() -> dict[str, set[str]]:
    global _API_SIGNATURES_CACHE
    if _API_SIGNATURES_CACHE is None:
        _API_SIGNATURES_CACHE = build_api_signatures()
    return _API_SIGNATURES_CACHE