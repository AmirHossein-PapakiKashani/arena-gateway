import json
import re
import uuid

TOOL_INSTRUCTION_TEMPLATE = """You are the model in a local coding agent harness.
The tools and agent loop execute LOCALLY in the client, not on Arena.
Use only the declared tools below. Do not pretend to execute tools or invent their results.
When a tool is needed, return one or more complete calls and WAIT for tool_response.
Tool call payloads MUST be valid JSON. Use forward slashes in ALL Windows paths,
for example E:/project/file.txt. Never put unescaped backslashes in JSON strings.
After a tool_response, inspect the actual result and decide the next action; a failure is not success.
Do not claim a file was written or tests passed without a successful tool result.
<tools>
{tools_json}
</tools>
Return a tool call exactly as:
<tool_call>
{{"name": "DECLARED_TOOL_NAME", "arguments": {{"parameter": "value"}}}}
</tool_call>
For a final conversational answer, use ordinary text without tool_call tags."""

TOOL_REGEX = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def inject_tools_into_prompt(messages: list[dict], tools: list[dict] | None = None) -> str:
    parts = []
    if tools:
        parts.append("[System Instructions]\n" + TOOL_INSTRUCTION_TEMPLATE.format(tools_json=json.dumps(tools, ensure_ascii=False)))
    for msg in messages:
        role = msg.get("role", "user").capitalize()
        content = msg.get("content") or ""
        if isinstance(content, list):
            content = "\n".join(p.get("text", "") for p in content if p.get("type") == "text")
        if msg.get("tool_calls"):
            content += "\n" + "\n".join("<tool_call>\n" + json.dumps({"name": tc["function"]["name"], "arguments": json.loads(tc["function"]["arguments"])}, ensure_ascii=False) + "\n</tool_call>" for tc in msg["tool_calls"])
        if msg.get("tool_call_id"):
            content = "<tool_response>\n" + json.dumps({"id": msg["tool_call_id"], "result": content}, ensure_ascii=False) + "\n</tool_response>"
        parts.append(f"[{role}]\n{content}")
    return "\n\n".join(parts)


def parse_response_for_tools(raw_text: str) -> tuple[str, list[dict] | None]:
    matches = list(TOOL_REGEX.finditer(raw_text))
    if not matches:
        matches = list(re.finditer(r'```(?:json)?\s*(\{\s*"name"\s*:.*?\})\s*```', raw_text, re.DOTALL))
    if not matches:
        return raw_text.strip(), None
    calls = []
    for match in matches:
        payload = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", match.group(1)).strip()
        try:
            data = json.loads(payload)
            name = data.get("name")
            args = data.get("arguments", data.get("args", {}))
            if not isinstance(name, str) or not name or name in {"NAME_OF_SELECTED_TOOL", "DECLARED_TOOL_NAME", "function_name"} or not isinstance(args, dict):
                return raw_text.strip(), None
            calls.append({"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                          "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
        except (ValueError, AttributeError, TypeError):
            return raw_text.strip(), None
    clean = raw_text
    for match in reversed(matches):
        clean = clean[:match.start()] + clean[match.end():]
    return clean.strip(), calls
