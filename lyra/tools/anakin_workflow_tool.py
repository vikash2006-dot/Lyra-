"""Anakin AI Workflow Tool implementation for LYRA.

Exposes Anakin AI applications and specialized pipelines as concrete LYRA tools,
supporting dynamic discovery, workflow execution, status inspection, and result formatting.
"""

import asyncio
import json
import logging
from typing import Any, Callable

from lyra.config.settings import Settings, load_settings
from lyra.core.exceptions import ToolError, ToolValidationError
from lyra.models.tools import ToolRequest, ToolResult
from lyra.observability.logging import get_logger, sanitize_text
from lyra.providers.anakin import AnakinClient, AnakinProvider
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel

logger = get_logger("tools.anakin_workflow")

DEFAULT_WORKFLOW_DEFINITIONS = [
    {
        "name": "research_workflow",
        "app_id": "research_assistant",
        "description": "Deeply researches a specified topic or query and produces a comprehensive factual summary.",
        "app_type": "quickapp",
        "trigger_phrases": ["research", "investigate", "study"],
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Subject, topic, or query to research."},
                "depth": {"type": "string", "enum": ["overview", "comprehensive", "technical"], "description": "Depth of analysis."},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "resume_analyzer",
        "app_id": "resume_evaluator",
        "description": "Analyzes resumes against job roles, identifying strengths, gaps, and improvements.",
        "app_type": "quickapp",
        "trigger_phrases": ["resume", "cv", "analyze my resume"],
        "input_schema": {
            "type": "object",
            "properties": {
                "resume_text": {"type": "string", "description": "Raw resume text or profile content to analyze."},
                "target_role": {"type": "string", "description": "Target job title or role to benchmark against."},
            },
            "required": ["resume_text"],
        },
    },
    {
        "name": "content_generator",
        "app_id": "content_creator",
        "description": "Generates structured content, documents, articles, or documentation templates.",
        "app_type": "quickapp",
        "trigger_phrases": ["generate content", "write article", "draft post"],
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Topic or briefing for content generation."},
            },
            "required": ["prompt"],
        },
    },
]


class AnakinWorkflowTool(Tool):
    """Dynamic tool wrapping an Anakin AI Quick App or Workflow application."""

    def __init__(
        self,
        name: str,
        app_id: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        app_type: str = "quickapp",
        trigger_phrases: list[str] | None = None,
        client: AnakinClient | None = None,
        permission_level: ToolPermissionLevel = ToolPermissionLevel.READ_ONLY,
    ) -> None:
        self._name = name
        self._app_id = app_id
        self._description = description
        self._input_schema = input_schema or {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Input prompt or payload for the workflow."},
            },
            "required": ["input"],
        }
        self._app_type = app_type.lower()
        self._trigger_phrases = trigger_phrases or []
        self._client = client
        self._permission_level = permission_level

    @property
    def name(self) -> str:
        return self._name

    @property
    def app_id(self) -> str:
        return self._app_id

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return self._permission_level

    @property
    def requires_network(self) -> bool:
        return True

    def _ensure_client(self) -> AnakinClient:
        """Lazily initialize AnakinClient from settings if not explicitly injected."""
        if not self._client:
            settings = load_settings()
            key = settings.anakin_api_key
            if not key or not key.strip():
                raise ToolError(
                    f"AnakinWorkflowTool '{self.name}' requires ANAKIN_API_KEY to be configured in .env."
                )
            self._client = AnakinClient(
                api_key=key,
                api_version=settings.anakin_api_version,
                base_url=settings.anakin_base_url,
                timeout=settings.request_timeout_seconds,
            )
        return self._client

    async def run_workflow(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute the configured Anakin workflow application."""
        client = self._ensure_client()
        logger.info(
            "Executing Anakin workflow '%s' (app_id: %s) with inputs: %s",
            self.name,
            self.app_id,
            list(inputs.keys()),
        )
        if self._app_type == "chatbot":
            content = str(inputs.get("content") or inputs.get("prompt") or inputs.get("input") or "")
            conv_id = inputs.get("conversation_id")
            return await client.run_chatbot(
                app_id=self.app_id,
                content=content,
                conversation_id=str(conv_id) if conv_id else None,
                stream=False,
            )
        return await client.run_quickapp(
            app_id=self.app_id,
            inputs=inputs,
            stream=False,
        )

    async def get_workflow_status(self, run_id: str) -> dict[str, Any]:
        """Check status of a running or completed workflow."""
        client = self._ensure_client()
        return await client.get_run_status(self.app_id, run_id)

    def handle_workflow_result(self, result: Any) -> str:
        """Normalize workflow output into a clean, human-readable response string."""
        if isinstance(result, str):
            return result.strip()
        if not isinstance(result, dict):
            return str(result)

        # Check standard result fields
        for field in ("result", "output", "answer", "content", "response", "text"):
            val = result.get(field)
            if isinstance(val, str) and val.strip():
                return val.strip()

        # Check choices
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message", {})
                if isinstance(msg, dict) and msg.get("content"):
                    return str(msg["content"]).strip()

        # Check nested data/result dict
        for k in ("data", "result"):
            nested = result.get(k)
            if isinstance(nested, dict):
                for sub in ("content", "text", "output", "result"):
                    if isinstance(nested.get(sub), str):
                        return nested[sub].strip()

        if result.get("status") in ("COMPLETED", "SUCCESS"):
            return f"Workflow '{self.name}' completed successfully."

        return json.dumps(result, indent=2)

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Inspect user query to decide if this specific workflow tool should handle it."""
        import re
        text = user_input.strip()
        cleaned = re.sub(r"(?i)^(?:hey|hi|hello|ok|okay)?\s*lyra[,:\s]*", "", text).strip()
        cleaned = re.sub(r"(?i)^(?:can|could|would)\s+you(?:\s+please)?\s+", "", cleaned)
        cleaned = re.sub(r"(?i)^please\s+", "", cleaned)
        lowered = cleaned.lower()

        # Check trigger phrases
        for phrase in self._trigger_phrases:
            if phrase in lowered:
                # Extract arguments based on workflow type
                if self.name in ("research_workflow", "anakin_research", "research_assistant"):
                    m = re.search(r"(?i)\bresearch\s+(?:the\s+)?(.+?)(?:\.|$)", cleaned)
                    topic = m.group(1).strip() if m else cleaned
                    return {"topic": topic, "input": topic, "prompt": topic}
                elif self.name in ("resume_analyzer", "anakin_resume"):
                    return {"resume_text": cleaned, "input": cleaned}
                return {"input": cleaned, "prompt": cleaned}

        return None

    def format_result(self, result: ToolResult) -> str:
        """Format workflow tool result for voice synthesis and chat presentation."""
        if not result.success:
            return f"Workflow '{self.name}' failed: {result.error}"
        out = result.output
        if isinstance(out, dict) and "formatted" in out:
            return str(out["formatted"])
        return self.handle_workflow_result(out)

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Execute the workflow asynchronously with error boundary."""
        args = dict(request.arguments)
        try:
            raw_result = await self.run_workflow(args)
            formatted = self.handle_workflow_result(raw_result)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output={
                    "workflow": self.name,
                    "app_id": self.app_id,
                    "raw": raw_result,
                    "formatted": formatted,
                },
            )
        except Exception as err:
            logger.error("AnakinWorkflowTool '%s' error: %s", self.name, err)
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Anakin workflow execution failed: {err}",
            )


def create_anakin_workflow_tools(
    settings: Settings | None = None,
    client: AnakinClient | None = None,
) -> list[AnakinWorkflowTool]:
    """Factory creating configured AnakinWorkflowTool instances from settings."""
    s = settings or load_settings()
    tools: list[AnakinWorkflowTool] = []

    # 1. Load user-configured workflows from settings
    configured = s.anakin_workflows
    seen_names: set[str] = set()

    for wf in configured:
        name = wf.get("name")
        app_id = wf.get("app_id") or s.anakin_app_id
        desc = wf.get("description", f"Anakin AI workflow for {name}")
        schema = wf.get("input_schema")
        app_type = wf.get("app_type", "quickapp")
        triggers = wf.get("trigger_phrases", [name.replace("_", " ")])

        if name and app_id:
            tools.append(
                AnakinWorkflowTool(
                    name=name,
                    app_id=str(app_id),
                    description=desc,
                    input_schema=schema,
                    app_type=app_type,
                    trigger_phrases=triggers,
                    client=client,
                )
            )
            seen_names.add(name)

    # 2. Add default built-in workflows if not overridden
    default_app_id = s.anakin_app_id or "default"
    for defn in DEFAULT_WORKFLOW_DEFINITIONS:
        name = defn["name"]
        if name not in seen_names:
            tools.append(
                AnakinWorkflowTool(
                    name=name,
                    app_id=defn["app_id"] if s.anakin_app_id is None else str(s.anakin_app_id),
                    description=defn["description"],
                    input_schema=defn["input_schema"],
                    app_type=defn["app_type"],
                    trigger_phrases=defn["trigger_phrases"],
                    client=client,
                )
            )

    return tools
