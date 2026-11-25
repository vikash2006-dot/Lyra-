"""Safe filesystem management and action execution tool for LYRA."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

from lyra.core.exceptions import ToolExecutionError, ToolPermissionError, ToolValidationError
from lyra.models.tools import ToolRequest, ToolResult
from lyra.observability.logging import get_logger
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel

logger = get_logger("tools.filesystem")

# Forbidden system directory prefixes and sensitive credential patterns
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "/etc",
    "/system",
    "/usr",
    "/bin",
    "/sbin",
    "/private/etc",
    "/private/var/root",
)

FORBIDDEN_COMPONENTS: tuple[str, ...] = (
    ".ssh",
    ".aws",
    ".gnupg",
    "keychains",
    ".bash_history",
    ".zsh_history",
)


def resolve_safe_path(raw_path: str, default_to_desktop: bool = False) -> Path:
    """Safely expand and resolve a filesystem path, enforcing sandbox boundaries."""
    if not raw_path or not raw_path.strip():
        raise ToolValidationError("Filesystem path cannot be empty.")

    cleaned = raw_path.strip()

    # Expand user tilde
    if cleaned.startswith("~"):
        expanded = os.path.expanduser(cleaned)
    elif cleaned.startswith("Desktop/") or cleaned.startswith("Desktop\\"):
        expanded = str(Path.home() / cleaned)
    elif default_to_desktop and not os.path.isabs(cleaned) and not cleaned.startswith("."):
        expanded = str(Path.home() / "Desktop" / cleaned)
    else:
        expanded = os.path.abspath(os.path.expanduser(cleaned))

    resolved = Path(expanded).resolve()
    resolved_str = str(resolved).lower()

    # Block access to protected system directory prefixes
    for prefix in FORBIDDEN_PREFIXES:
        if resolved_str == prefix or resolved_str.startswith(prefix + "/"):
            raise ToolPermissionError(
                f"Access denied: Path '{raw_path}' touches protected system directory '{prefix}'."
            )

    # Block access to sensitive credential components and .env files
    if resolved.name.startswith(".env") or resolved.name == ".env":
        raise ToolPermissionError(f"Access denied: Path '{raw_path}' touches protected environment secret file.")

    for comp in FORBIDDEN_COMPONENTS:
        if comp in resolved.parts or any(p.lower() == comp for p in resolved.parts):
            raise ToolPermissionError(
                f"Access denied: Path '{raw_path}' touches protected credential component '{comp}'."
            )

    return resolved


def parse_folder_structure(raw: str | list[str], root_name: str | None = None) -> list[str]:
    """Parse hierarchical, indented, newline-separated, or natural language folder paths."""
    if isinstance(raw, list):
        items = [str(x).strip().strip("/\\") for x in raw if str(x).strip()]
        if root_name:
            clean_root = root_name.strip().strip("/\\")
            return [clean_root] + [f"{clean_root}/{item}" for item in items]
        return items

    text = str(raw).strip()
    # Check natural language: "with src, tests and docs" or "Projects, Notes and Documents"
    if "\n" not in text and ("," in text or " and " in text or text.lower().startswith("with ")):
        cleaned = re.sub(r"(?i)^with\s+", "", text).strip()
        parts = re.split(r",\s*|\s+and\s+", cleaned)
        items = [p.strip().strip("/\\") for p in parts if p.strip()]
        if root_name:
            clean_root = root_name.strip().strip("/\\")
            return [clean_root] + [f"{clean_root}/{item}" for item in items]
        return items

    # Check single-line slash-separated siblings/hierarchy: e.g. "AI/backend/frontend/data"
    if "\n" not in text and "/" in text and not re.search(r"\.[a-zA-Z0-9]{1,8}$", text):
        slash_parts = [p.strip().strip("/\\") for p in text.split("/") if p.strip()]
        if len(slash_parts) >= 2:
            root = slash_parts[0]
            items = [root]
            # Add sibling subdirectories under root
            for sub in slash_parts[1:]:
                sub_path = f"{root}/{sub}"
                if sub_path not in items:
                    items.append(sub_path)
            # Also add progressive nested paths
            accum = root
            for sub in slash_parts[1:]:
                accum = f"{accum}/{sub}"
                if accum not in items:
                    items.append(accum)
            return items

    # Line-by-line parsing (supporting indented trees or plain lists)
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return [root_name] if root_name else []

    # Stack tracking: [(indent_level, accumulated_path)]
    result_paths: list[str] = []
    stack: list[tuple[int, str]] = []

    # If root_name provided and not already in first line, initialize stack with root_name
    if root_name:
        clean_root = root_name.strip().strip("/\\")
        result_paths.append(clean_root)
        stack.append((-1, clean_root))

    for line in lines:
        indent = len(line) - len(line.lstrip(" "))
        item = line.strip().strip("/\\")
        if not item:
            continue

        while stack and stack[-1][0] >= indent:
            stack.pop()

        if stack:
            parent_path = stack[-1][1]
            full_path = f"{parent_path}/{item}"
        else:
            full_path = item

        stack.append((indent, full_path))
        if full_path not in result_paths:
            result_paths.append(full_path)

    return result_paths


class FilesystemTool(Tool):
    """Safely executes real filesystem actions with path sandboxing and confirmation enforcement."""

    def __init__(self, default_base_dir: Path | None = None) -> None:
        self.default_base_dir = default_base_dir or (Path.home() / "Desktop")

    @property
    def name(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return (
            "Perform real, safe filesystem actions on macOS: create folders, create files, "
            "create folder structures, read files, list directories, rename, move, open in Finder, and delete (confirmation required)."
        )

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create_directory",
                        "create_file",
                        "create_structure",
                        "read_file",
                        "list_directory",
                        "rename",
                        "move",
                        "delete",
                        "open_path",
                    ],
                    "description": "Filesystem action to execute.",
                },
                "path": {
                    "type": "string",
                    "description": "Target file or directory path.",
                },
                "structure": {
                    "description": "Folder hierarchy or list of paths to create for create_structure action.",
                },
                "root_name": {
                    "type": "string",
                    "description": "Optional root directory name for create_structure.",
                },
                "base_path": {
                    "type": "string",
                    "description": "Base directory for structure creation (defaults to Desktop).",
                },
                "content": {
                    "type": "string",
                    "description": "Text content for create_file action.",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination path for rename or move actions.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Must be true to execute destructive operations like delete.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def get_action_permission_level(self, action: str) -> ToolPermissionLevel:
        """Determine permission level for a given filesystem action."""
        if action in ("read_file", "list_directory"):
            return ToolPermissionLevel.READ_ONLY
        if action in ("create_directory", "create_file", "create_structure", "open_path"):
            return ToolPermissionLevel.LOW_RISK
        if action in ("rename", "move", "delete"):
            return ToolPermissionLevel.CONFIRMATION_REQUIRED
        return ToolPermissionLevel.HIGH_RISK

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Detect natural language filesystem intents."""
        text = user_input.strip()
        lowered = text.lower()

        # 0. Folder structure intents
        # E.g. "Create a folder structure called Project with src, tests and docs"
        m_struct_called = re.search(
            r"(?i)\b(?:create|make)\s+(?:a\s+)?folder\s+structure\s+(?:called|named)\s+['\"]?([a-zA-Z0-9_\- ]+?)['\"]?\s+(?:with\s+)?(.+)$",
            text,
        )
        if m_struct_called:
            root = m_struct_called.group(1).strip()
            rest = m_struct_called.group(2).strip()
            return {"action": "create_structure", "root_name": root, "structure": rest}

        # E.g. "Inside College create Projects, Notes and Documents"
        m_inside_struct = re.search(
            r"(?i)\binside\s+['\"]?([a-zA-Z0-9_\- ]+?)['\"]?\s+(?:create|make)\s+(.+)$",
            text,
        )
        if m_inside_struct:
            root = m_inside_struct.group(1).strip()
            rest = m_inside_struct.group(2).strip()
            return {"action": "create_structure", "root_name": root, "structure": rest}

        # E.g. "Create this project structure on my Desktop:\n..." or "Create this structure:\n..."
        if re.search(r"(?i)\b(?:create|make)\s+this\s+(?:project\s+)?structure", text):
            parts = re.split(r"(?i)\bstructure(?:\s+on\s+(?:my\s+)?desktop)?\s*[:\n]", text, maxsplit=1)
            raw_struct = parts[1].strip() if len(parts) > 1 else text
            return {"action": "create_structure", "structure": raw_struct}

        # 1. Create folder / directory
        match_folder = re.search(
            r"(?i)\b(?:create|make|new)\s+(?:a\s+)?(?:folder|directory)\s+(?:on\s+(?:my\s+)?desktop\s+)?(?:called|named)?\s*['\"]?([a-zA-Z0-9_\-./ ]+?)['\"]?(?:\s+on\s+(?:my\s+)?desktop)?(?:\.|$)",
            text,
        )
        if match_folder and not ("file" in lowered and "inside" in lowered):
            folder_name = match_folder.group(1).strip()
            # Clean up trailing words
            folder_name = re.sub(r"(?i)\s+(?:on|in|inside)\s+(?:my\s+)?desktop$", "", folder_name).strip()
            if folder_name:
                is_desktop = "desktop" in lowered
                path = str(Path.home() / "Desktop" / folder_name) if is_desktop else folder_name
                return {"action": "create_directory", "path": path}

        # 2. Create file
        match_file = re.search(
            r"(?i)\b(?:create|make|write|touch)\s+(?:a\s+)?(?:file|document)\s+(?:called|named)?\s*['\"]?([a-zA-Z0-9_\-./ ]+\.[a-zA-Z0-9]+)['\"]?",
            text,
        )
        if match_file:
            filename = match_file.group(1).strip()
            is_desktop = "desktop" in lowered
            path = str(Path.home() / "Desktop" / filename) if is_desktop else filename
            return {"action": "create_file", "path": path, "content": ""}

        # 3. Open folder / path
        match_open = re.search(
            r"(?i)\b(?:open|show|reveal)\s+(?:my\s+)?([a-zA-Z0-9_\-./ ]+?)\s+(?:folder|directory)\b",
            text,
        )
        if match_open:
            target = match_open.group(1).strip()
            if target.lower() == "desktop":
                return {"action": "open_path", "path": str(Path.home() / "Desktop")}
            return {"action": "open_path", "path": str(Path.home() / "Desktop" / target)}

        # 4. Delete folder / file
        match_del = re.search(
            r"(?i)\b(?:delete|remove|erase)\s+(?:the\s+)?([a-zA-Z0-9_\-./ ]+?)(?:\s+(?:folder|directory|file))?(?:\.|$)",
            text,
        )
        if match_del and not any(w in lowered for w in ("history", "message", "chat", "session")):
            target = match_del.group(1).strip()
            if target:
                path = str(Path.home() / "Desktop" / target)
                return {"action": "delete", "path": path, "confirmed": False}

        # 5. Rename folder / file
        match_rename = re.search(
            r"(?i)\brename\s+(?:the\s+)?([a-zA-Z0-9_\-./ ]+?)(?:\s+(?:folder|directory|file))?\s+to\s+['\"]?([a-zA-Z0-9_\-./ ]+?)['\"]?(?:\.|$)",
            text,
        )
        if match_rename:
            src = match_rename.group(1).strip()
            dest = match_rename.group(2).strip()
            return {
                "action": "rename",
                "path": str(Path.home() / "Desktop" / src),
                "destination": str(Path.home() / "Desktop" / dest),
            }

        return None

    def format_result(self, result: ToolResult) -> str:
        """Format filesystem results into clean, conversational statements."""
        if not result.success:
            if result.metadata.get("requires_confirmation"):
                path_name = Path(result.metadata.get("path", "item")).name
                return (
                    f"Deleting '{path_name}' is a destructive action. "
                    "Are you sure you want to delete it? Please say 'yes' or 'confirm' to proceed."
                )
            return f"I couldn't perform the filesystem action: {result.error}"

        out = result.output if isinstance(result.output, dict) else {}
        action = out.get("action")
        path_str = out.get("path", "")
        path_name = Path(path_str).name if path_str else "item"

        if action == "create_structure":
            root_name = out.get("root_name")
            count = out.get("count", 0)
            if root_name:
                return f"Done, I created the {root_name} folder structure with {count} directories on your Desktop."
            return f"Done, I created the requested structure with {count} directories."
        elif action == "create_directory":
            if "Desktop" in path_str:
                return f"Done, I created {path_name} on your Desktop."
            return f"Done, I created the folder '{path_name}' at {path_str}."
        elif action == "create_file":
            if "Desktop" in path_str:
                return f"Done, I created {path_name} on your Desktop."
            return f"Done, I created the file '{path_name}' at {path_str}."
        elif action == "delete":
            return f"Done, I have deleted '{path_name}'."
        elif action == "rename":
            new_name = Path(out.get("destination", "")).name
            return f"Done, I renamed '{path_name}' to '{new_name}'."
        elif action == "move":
            dest_name = Path(out.get("destination", "")).name
            return f"Done, I moved '{path_name}' to '{dest_name}'."
        elif action == "open_path":
            return f"Opened '{path_name}' in Finder."
        elif action == "read_file":
            content = out.get("content", "")
            return f"Content of '{path_name}':\n\n{content}"
        elif action == "list_directory":
            entries = out.get("entries", [])
            names = [e.get("name") for e in entries[:20]]
            return f"Found {len(entries)} items in '{path_name}': {', '.join(names)}"

        return result.to_text()

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Execute a validated filesystem request."""
        args = request.arguments
        action = args.get("action") or args.get("command")
        if not action:
            return ToolResult(tool_name=self.name, success=False, error="Missing required 'action' argument.")

        raw_path = args.get("path")
        if not raw_path and action not in ("list_directory", "create_structure"):
            return ToolResult(tool_name=self.name, success=False, error="Missing required 'path' argument.")

        # Default path to desktop if not provided for list
        if not raw_path:
            raw_path = str(self.default_base_dir)

        try:
            target_path = resolve_safe_path(raw_path, default_to_desktop=True)
        except Exception as path_err:
            return ToolResult(tool_name=self.name, success=False, error=str(path_err))

        confirmed = bool(args.get("confirmed", False))

        try:
            # 0. CREATE STRUCTURE
            if action == "create_structure":
                raw_struct = args.get("structure", "")
                root_name = args.get("root_name")
                base_dir = args.get("base_path") or str(self.default_base_dir)
                base_p = resolve_safe_path(base_dir, default_to_desktop=True)

                parsed_paths = parse_folder_structure(raw_struct, root_name=root_name)
                if not parsed_paths and root_name:
                    parsed_paths = [root_name]

                created: list[str] = []
                for rel_path in parsed_paths:
                    item_path = resolve_safe_path(str(base_p / rel_path))
                    is_file = bool(re.search(r"\.[a-zA-Z0-9]{1,8}$", item_path.name))
                    if is_file:
                        item_path.parent.mkdir(parents=True, exist_ok=True)
                        if not item_path.exists():
                            item_path.write_text("", encoding="utf-8")
                    else:
                        item_path.mkdir(parents=True, exist_ok=True)

                    if not item_path.exists():
                        return ToolResult(
                            tool_name=self.name,
                            success=False,
                            error=f"Verification failed: could not create '{item_path}'",
                        )
                    created.append(str(item_path))

                logger.info("Created structure with %d items under '%s'", len(created), base_p)
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "create_structure",
                        "root_name": root_name,
                        "base_path": str(base_p),
                        "created_paths": created,
                        "count": len(created),
                        "verified": True,
                    },
                    metadata={"path": str(base_p)},
                )
            # 1. CREATE DIRECTORY
            elif action == "create_directory":
                target_path.mkdir(parents=True, exist_ok=True)
                logger.info("Created directory: '%s'", target_path)
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "create_directory",
                        "path": str(target_path),
                        "name": target_path.name,
                        "created": True,
                    },
                    metadata={"path": str(target_path)},
                )

            # 2. CREATE FILE
            elif action == "create_file":
                # Ensure parent folder exists
                target_path.parent.mkdir(parents=True, exist_ok=True)
                content = args.get("content", "")
                target_path.write_text(content, encoding="utf-8")
                logger.info("Created file: '%s' (%d bytes)", target_path, len(content))
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "create_file",
                        "path": str(target_path),
                        "name": target_path.name,
                        "size_bytes": len(content),
                        "created": True,
                    },
                    metadata={"path": str(target_path)},
                )

            # 3. READ FILE
            elif action == "read_file":
                if not target_path.exists() or not target_path.is_file():
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error=f"File not found: '{target_path}'",
                    )
                text_content = target_path.read_text(encoding="utf-8", errors="replace")[:10000]
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "read_file",
                        "path": str(target_path),
                        "name": target_path.name,
                        "content": text_content,
                    },
                    metadata={"path": str(target_path)},
                )

            # 4. LIST DIRECTORY
            elif action == "list_directory":
                if not target_path.exists() or not target_path.is_dir():
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error=f"Directory not found: '{target_path}'",
                    )
                entries = []
                for entry in target_path.iterdir():
                    entries.append({
                        "name": entry.name,
                        "is_dir": entry.is_dir(),
                        "size": entry.stat().st_size if entry.is_file() else 0,
                    })
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "list_directory",
                        "path": str(target_path),
                        "entries": entries,
                    },
                    metadata={"path": str(target_path)},
                )

            # 5. RENAME / MOVE
            elif action in ("rename", "move"):
                raw_dest = args.get("destination")
                if not raw_dest:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error=f"Action '{action}' requires a 'destination' argument.",
                    )
                dest_path = resolve_safe_path(raw_dest, default_to_desktop=True)
                if not target_path.exists():
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error=f"Source path '{target_path}' does not exist.",
                    )
                shutil.move(str(target_path), str(dest_path))
                logger.info("%s from '%s' to '%s'", action.capitalize(), target_path, dest_path)
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": action,
                        "path": str(target_path),
                        "destination": str(dest_path),
                    },
                    metadata={"path": str(dest_path)},
                )

            # 6. DELETE (Confirmation Required)
            elif action == "delete":
                if not target_path.exists():
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error=f"Path not found: '{target_path}'",
                    )
                if not confirmed:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error=f"Confirmation required before deleting '{target_path.name}'.",
                        output={
                            "requires_confirmation": True,
                            "action": "delete",
                            "path": str(target_path),
                        },
                        metadata={
                            "requires_confirmation": True,
                            "action": "delete",
                            "path": str(target_path),
                        },
                    )

                if target_path.is_dir():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
                logger.info("Deleted '%s'", target_path)
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "delete",
                        "path": str(target_path),
                        "deleted": True,
                    },
                    metadata={"path": str(target_path)},
                )

            # 7. OPEN PATH (e.g. in macOS Finder)
            elif action == "open_path":
                if not target_path.exists():
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error=f"Path not found: '{target_path}'",
                    )
                if sys.platform == "darwin":
                    subprocess.run(["open", str(target_path)], check=False)
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "open_path",
                        "path": str(target_path),
                        "opened": True,
                    },
                    metadata={"path": str(target_path)},
                )

            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Unrecognized filesystem action '{action}'.",
            )

        except Exception as err:
            logger.error("Filesystem execution error for action '%s': %s", action, err)
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(err),
                metadata={"path": str(target_path)},
            )
