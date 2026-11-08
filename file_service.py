import difflib
from pathlib import Path
from typing import Any

def _resolve_safe_path(workspace: str, relative_path: str) -> Path:
    ws_path = Path(workspace).resolve()
    target_path = (ws_path / relative_path).resolve()
    try:
        target_path.relative_to(ws_path)
    except ValueError:
        raise ValueError(f"Path traversal detected: {relative_path} outside {workspace}")
    return target_path

def generate_diff(workspace: str, relative_path: str, new_content: str) -> dict[str, Any]:
    target = _resolve_safe_path(workspace, relative_path)
    if not target.exists():
        old_lines = []
        is_new = True
    else:
        old_lines = target.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        is_new = False
    
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{relative_path}",
        tofile=f"b/{relative_path}"
    )
    return {
        "is_new": is_new,
        "diff": "".join(diff),
        "target_path": str(target)
    }

def write_workspace_file(workspace: str, relative_path: str, new_content: str) -> dict[str, Any]:
    target = _resolve_safe_path(workspace, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_content, encoding="utf-8")
    return {
        "status": "success",
        "full_path": str(target),
        "bytes_written": len(new_content.encode("utf-8"))
    }
