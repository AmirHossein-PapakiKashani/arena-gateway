from pathlib import Path
from typing import Any

TEXT_EXTENSIONS = {
    ".cs", ".py", ".ts", ".js", ".go", ".rs", ".java", ".cpp", ".c", ".h",
    ".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".sql", ".sh", ".ps1", ".html", ".css", ".xml"
}

def extract_text_from_bytes(filename: str, content: bytes) -> dict[str, Any]:
    ext = Path(filename).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="replace")
            
        return {
            "status": "success",
            "filename": filename,
            "type": "code" if ext not in (".txt", ".md") else "text",
            "char_count": len(text),
            "text": text
        }
    
    # Non-code/non-text files fall back to binary summary
    return {
        "status": "binary_fallback",
        "filename": filename,
        "type": "binary",
        "char_count": 0,
        "text": f"[Attached binary file: {filename}, size: {len(content)} bytes]"
    }
