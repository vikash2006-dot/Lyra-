"""Unit tests for AnakinWorkflowTool and dynamic workflow discovery."""

import asyncio
import json
from unittest.mock import MagicMock
import pytest

from lyra.config.settings import Settings
from lyra.models.tools import ToolRequest
from lyra.providers.anakin import AnakinClient
from lyra.tools.anakin_workflow_tool import AnakinWorkflowTool, create_anakin_workflow_tools


@pytest.fixture
def mock_client() -> AnakinClient:
    client = AnakinClient(api_key="ask_mock_123", timeout=5.0)
    client._execute_http = MagicMock(return_value={"result": "Workflow executed successfully."})
    return client


def test_anakin_workflow_tool_metadata(mock_client: AnakinClient) -> None:
    tool = AnakinWorkflowTool(
        name="custom_research",
        app_id="app_12345",
        description="Researches specified topic",
        client=mock_client,
    )
    assert tool.name == "custom_research"
    assert tool.app_id == "app_12345"
    assert "Researches" in tool.description
    assert tool.requires_network is True
    assert "input" in tool.input_schema["properties"]


def test_anakin_workflow_tool_execution(mock_client: AnakinClient) -> None:
    tool = AnakinWorkflowTool(
        name="resume_analyzer",
        app_id="app_resume_99",
        description="Analyzes resumes",
        client=mock_client,
    )
    req = ToolRequest(
        tool_name="resume_analyzer",
        arguments={"resume_text": "Experienced Python Software Engineer with AI knowledge."},
    )
    res = asyncio.run(tool.execute(req))
    assert res.success is True
    assert "Workflow executed successfully." in res.output["formatted"]


def test_anakin_workflow_status_and_formatting(mock_client: AnakinClient) -> None:
    mock_client._execute_http = MagicMock(return_value={"status": "COMPLETED", "id": "run_888"})
    tool = AnakinWorkflowTool(
        name="test_wf",
        app_id="app_test",
        description="Test",
        client=mock_client,
    )
    status = asyncio.run(tool.get_workflow_status("run_888"))
    assert status.get("status") == "COMPLETED"

    formatted = tool.handle_workflow_result({"output": "Formatted answer text"})
    assert formatted == "Formatted answer text"


def test_anakin_workflow_can_handle(mock_client: AnakinClient) -> None:
    tool = AnakinWorkflowTool(
        name="research_workflow",
        app_id="app_research",
        description="Deep research",
        trigger_phrases=["research", "investigate"],
        client=mock_client,
    )
    handled = tool.can_handle("Lyra, research the best free Python resources")
    assert handled is not None
    assert "Python resources" in handled.get("topic", "")

    not_handled = tool.can_handle("What time is it in Tokyo?")
    assert not_handled is None


def test_create_anakin_workflow_tools_discovery() -> None:
    settings = Settings(
        anakin_api_key="ask_test_123",
        anakin_app_id="default_app_777",
        anakin_workflows=(
            {
                "name": "custom_agent",
                "app_id": "app_agent_001",
                "description": "Custom agent pipeline",
            },
        ),
    )
    tools = create_anakin_workflow_tools(settings=settings)
    tool_names = [t.name for t in tools]

    assert "custom_agent" in tool_names
    assert "research_workflow" in tool_names
    assert "resume_analyzer" in tool_names
