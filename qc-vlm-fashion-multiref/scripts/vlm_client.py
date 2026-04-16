from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


DEFAULT_MCP_URL = (
    "https://be.omnimcp.ai/api/v1/mcp/"
    "c113d8a2-dc6f-4491-89b7-e6be36b9e3a5/"
    "689eb17c8dde37087f88628c/sse?user-id=6888745cfcaf9f1463a1ae0b"
)
DEFAULT_MODEL = "gemini-3-flash"
TOOL_NAME = "llm-multimodal-invoke"


@dataclass
class WFMultimodalClient:
    mcp_url: str = DEFAULT_MCP_URL
    default_model: str = DEFAULT_MODEL
    wf_binary: str = "wf"
    timeout_seconds: int = 240

    def invoke(
        self,
        prompt: str,
        message: str,
        images: list[str],
        response_schema: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Any:
        command = [
            self.wf_binary,
            "tool",
            "--mcp",
            self.mcp_url,
            TOOL_NAME,
            "--model",
            model or self.default_model,
            "--prompt",
            prompt,
            "--message",
            message,
        ]
        if images:
            command.extend(["--images", json.dumps(images, ensure_ascii=False)])
        if response_schema is not None:
            command.extend(
                ["--response-schema", json.dumps(response_schema, ensure_ascii=False)]
            )

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "wf multimodal invocation failed.\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"wf multimodal invocation returned non-JSON stdout:\n{completed.stdout}"
            ) from exc

        result = payload.get("result")
        if isinstance(result, str):
            return _parse_json_like_string(result)
        return result


def _parse_json_like_string(value: str) -> Any:
    candidate = value.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return {"raw_result": value}
