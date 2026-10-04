from datetime import datetime, timedelta, timezone
import getpass
import json
import sys
from typing import Any, Sequence

from lyra.auth.local import LocalAuthProvider
from lyra.auth.manager import AuthManager
from lyra.automation.executor import AutomationExecutor
from lyra.automation.scheduler import Scheduler
from lyra.automation.sqlite_store import SQLiteAutomationStore
from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.session import Session
from lyra.config.settings import load_settings
from lyra.core.exceptions import AuthError, AutomationError, ConfigurationError, LYRAError
from lyra.memory.manager import MemoryManager
from lyra.memory.policy import MemoryPolicy
from lyra.memory.sqlite_repository import SQLiteMemoryRepository
from lyra.models.automation import (
    IntervalTrigger,
    OneTimeTrigger,
    ReminderAction,
    ToolAction,
)
from lyra.models.stream import StreamError, TextDelta
from lyra.observability.logging import get_logger, sanitize_text, setup_logging
from lyra.providers.anakin import AnakinProvider
from lyra.providers.cerebras import CerebrasProvider
from lyra.providers.gemini import GeminiProvider
from lyra.providers.groq import GroqProvider
from lyra.providers.local import LocalProvider, LocalProviderConfig
from lyra.providers.openrouter import OpenRouterProvider
from lyra.providers.xai import XAIProvider
from lyra.browser.manager import BrowserManager
from lyra.computer.controller import ComputerController
from lyra.routing.router import ModelRouter
from lyra.routing.strategies import PriorityFallbackStrategy
from lyra.tools.browser_tool import BrowserTool
from lyra.tools.computer_tool import ComputerTool
from lyra.tools.executor import ToolExecutor
from lyra.tools.file_tool import FileTool
from lyra.tools.filesystem import FilesystemTool
from lyra.tools.maps import MapsTool
from lyra.tools.memory_tool import MemoryTool
from lyra.tools.news import NewsTool
from lyra.tools.registry import ToolRegistry
from lyra.tools.keyboard_mouse_tool import KeyboardTool, MouseTool
from lyra.tools.media_tool import MediaTool
from lyra.tools.notes_tool import NotesTool
from lyra.tools.search import SearchTool
from lyra.tools.system_tool import SystemTool
from lyra.tools.time_tool import TimeTool
from lyra.tools.vision_tool import VisionTool
from lyra.tools.weather import WeatherTool
from lyra.learning.repository import SQLiteLearningRepository
from lyra.learning.service import LearningService
from lyra.tools.learning_tools import create_learning_tools
from lyra.tools.anakin_workflow_tool import create_anakin_workflow_tools


def _stream_and_display(
    orchestrator: CompanionOrchestrator,
    session: Session,
    prompt: str,
    parts: Sequence[Any] | None = None,
) -> None:
    """Run stream_turn and progressively print delta tokens to stdout."""
    import asyncio

    async def _runner() -> None:
        sys.stdout.write("LYRA: ")
        sys.stdout.flush()
        async for event in orchestrator.stream_turn(session, prompt, parts=parts):
            if isinstance(event, TextDelta):
                sys.stdout.write(event.delta)
                sys.stdout.flush()
            elif isinstance(event, StreamError):
                sys.stdout.write(f"\n[Streaming Error: {event.error_message}]")
                sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()

    asyncio.run(_runner())


def _run_diagnostic(settings: Settings, router: ModelRouter) -> int:
    """Run safe diagnostics to verify configuration, key detection, and provider health without exposing secrets."""
    print("========================================")
    print("         LYRA SYSTEM DIAGNOSTICS        ")
    print("========================================")

    # 1. Environment & Key detection
    has_gemini = bool(settings.gemini_api_key and settings.gemini_api_key.strip())
    print(f"Gemini API key configured: {'YES' if has_gemini else 'NO'}")
    if has_gemini:
        k = settings.gemini_api_key.strip()
        print(f"Gemini API key length: {len(k)} characters")
        print(f"Gemini API key prefix: {k[:4]}...")

    # 2. Gemini Client Initialization
    gemini_prov = router.get_provider("gemini")
    print(f"Gemini client initialized: {'YES' if gemini_prov else 'NO'}")
    print(f"Gemini default model: {settings.gemini_model}")
    print(f"Gemini base URL: {settings.gemini_base_url}")

    # 3. Provider Pool Status
    print("\nAI Provider Pool Configuration:")
    for prov in ("gemini", "xai", "groq", "cerebras", "openrouter", "anakin", "local"):
        p = router.get_provider(prov)
        name = "Grok" if prov == "xai" else ("Anakin" if prov == "anakin" else ("OpenRouter" if prov == "openrouter" else ("Ollama" if prov == "local" else prov.capitalize())))
        status = router.tracker.get_status(prov).value if p else "NOT_CONFIGURED"
        is_cfg = p.is_configured if p else False
        print(f"  {name:12s}: Configured={'YES' if is_cfg else 'NO'}, Status={status}")

    # 4. Safe Live Auth Test (without exposing secrets)
    if has_gemini and gemini_prov:
        print("\nTesting Gemini connectivity & authentication...")
        import asyncio
        from lyra.models.messages import AIRequest, Message, Role
        from lyra.routing.health import classify_failure
        req = AIRequest(messages=(Message(role=Role.USER, content="ping"),), max_tokens=5)
        try:
            resp = asyncio.run(gemini_prov.generate(req))
            print("Gemini authentication successful: YES")
            print(f"Gemini model available: YES ({resp.model})")
        except Exception as e:
            cat = classify_failure(e)
            print(f"Gemini authentication successful: NO ({cat.value})")
            print(f"Gemini diagnostic error detail: {sanitize_text(str(e))[:160]}")

    print("========================================")
    return 0


def _print_help() -> None:
    """Print command-line usage information."""
    help_text = """LYRA — Modular Personal AI Operating System

Usage:
  lyra [options] [prompt...]
  lyra voice [options]
  lyra --help

Modes:
  (no arguments)        Start interactive conversational text companion
  voice, --voice        Start continuous voice conversation (mic -> Gemini -> speakers)
  <prompt>              Run single-shot query with live streaming response

Options:
  -i, --image <path>    Attach an image for visual inspection
  -f, --file <path>     Attach a document or file for analysis
  -u, --user <name>     Bind session to a specific registered user identity
  --offline             Force local AI execution and disable external network tools
  -h, --help            Display this help documentation
"""
    print(help_text)


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point for LYRA with companion conversation loop, voice, and streaming."""
    try:
        raw_args = list(argv) if argv is not None else sys.argv[1:]
        if any(h in raw_args for h in ("--help", "-h", "help")):
            _print_help()
            return 0

        # 1. Load configuration
        settings = load_settings()

        # 2. Initialize diagnostic logging
        setup_logging(log_level=settings.log_level)
        logger = get_logger("cli")
        logger.debug("Configuration successfully loaded.")
        logger.info(
            "LYRA runtime initialized (Environment: %s, Log Level: %s)",
            settings.lyra_env,
            settings.log_level,
        )

        is_voice_mode = any(v in raw_args for v in ("voice", "--voice"))
        offline_flag = "--offline" in raw_args
        args = [a for a in raw_args if a not in ("--offline", "voice", "--voice")]
        is_offline = settings.offline_mode or offline_flag

        # 3. Initialize Provider Pool and Model Router
        local_provider = LocalProvider(config=LocalProviderConfig.from_settings(settings))
        gemini_provider = GeminiProvider(
            api_key=settings.gemini_api_key,
            default_model=settings.gemini_model,
            timeout=settings.request_timeout_seconds,
            base_url=settings.gemini_base_url,
        )
        xai_provider = XAIProvider(
            api_key=settings.xai_api_key,
            default_model=settings.xai_model,
            timeout=settings.request_timeout_seconds,
        )
        providers = [
            gemini_provider,
            xai_provider,
            GroqProvider(),
            CerebrasProvider(),
            OpenRouterProvider(),
            AnakinProvider(),
            local_provider,
        ]
        strategy = PriorityFallbackStrategy(settings.provider_priority, offline_mode=is_offline)
        router = ModelRouter(providers=providers, strategy=strategy, offline_mode=is_offline)

        if any(d in raw_args for d in ("--doctor", "doctor", "--diagnose", "diagnose")):
            return _run_diagnostic(settings, router)

        # 4. Initialize Memory Subsystem
        memory_repo = SQLiteMemoryRepository(db_path=settings.memory_db_path)
        memory_policy = MemoryPolicy()
        memory_manager = MemoryManager(repository=memory_repo, policy=memory_policy)

        # 5. Initialize Tool Registry and Executor
        browser_manager = BrowserManager(settings=settings)
        browser_tool = BrowserTool(manager=browser_manager)

        use_mock = "pytest" in sys.modules or not (sys.platform == "darwin")
        computer_controller = ComputerController.from_settings(settings=settings, use_mock=use_mock)
        computer_controller.enabled = True
        computer_tool = ComputerTool(controller=computer_controller)

        learning_repo = SQLiteLearningRepository(db_path=settings.learning_db_path)
        learning_service = LearningService(
            repository=learning_repo,
            router=router,
            memory_manager=memory_manager,
            db_path=settings.learning_db_path,
        )
        learning_tools = create_learning_tools(learning_service)

        tools = [
            TimeTool(),
            WeatherTool(),
            SearchTool(),
            NewsTool(),
            MapsTool(),
            MemoryTool(memory_manager=memory_manager),
            FileTool(),
            FilesystemTool(),
            VisionTool(),
            browser_tool,
            computer_tool,
            SystemTool(),
            NotesTool(),
            MediaTool(),
            KeyboardTool(),
            MouseTool(),
        ]
        tools.extend(learning_tools)
        anakin_workflow_tools = create_anakin_workflow_tools(settings=settings)
        tools.extend(anakin_workflow_tools)
        tool_registry = ToolRegistry(tools=tools)
        learning_service.tool_registry = tool_registry
        tool_executor = ToolExecutor(registry=tool_registry, offline_mode=is_offline)

        # 6. Initialize Automation Subsystem
        automation_store = SQLiteAutomationStore(db_path=settings.automation_db_path)
        automation_executor = AutomationExecutor(
            store=automation_store,
            tool_executor=tool_executor,
            notification_callback=lambda uid, msg: sys.stdout.write(f"\n[REMINDER: {msg}]\n"),
        )
        scheduler = Scheduler(
            store=automation_store,
            executor=automation_executor,
            poll_interval_seconds=settings.automation_poll_interval_seconds,
        )

        # 7. Initialize Auth Subsystem
        auth_provider = LocalAuthProvider(
            db_path=settings.auth_db_path,
            token_ttl_seconds=settings.auth_token_ttl_seconds,
            max_failed_attempts=settings.auth_max_failed_attempts,
            lockout_duration_seconds=settings.auth_lockout_duration_seconds,
        )
        auth_manager = AuthManager(
            provider=auth_provider,
            memory_manager=memory_manager,
            scheduler=scheduler,
        )

        # 8. Initialize Companion Orchestrator & Session
        orchestrator = CompanionOrchestrator(
            router=router,
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            memory_manager=memory_manager,
            offline_mode=is_offline,
            learning_service=learning_service,
        )
        session = Session()

        # Startup banner
        print("LYRA starting...")
        print(f"Environment: {settings.lyra_env}")
        if is_offline:
            print("[OFFLINE MODE] Local AI provider active. External cloud APIs and search disabled.")
        print("\nLYRA is ready.")

        # Handle optional -u / --user flag across all modes
        remaining_args: list[str] = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in ("--user", "-u") and i + 1 < len(args):
                uname = args[i + 1]
                user = auth_manager.get_user_by_username(uname)
                if user:
                    session.bind_user(user)
                    logger.info("Bound session to user '%s' (%s)", uname, user.id)
                else:
                    sys.stderr.write(f"Warning: User '{uname}' not found.\n")
                i += 2
            else:
                remaining_args.append(arg)
                i += 1
        args = remaining_args

        # Voice Mode execution
        if is_voice_mode:
            import asyncio
            from lyra.voice.capture import MicrophoneCapture
            from lyra.voice.player import AudioPlayer
            from lyra.voice.conversation import VoiceConversationManager
            from lyra.voice.providers.free_stt import FreeSTTProvider
            from lyra.voice.providers.system import SystemTTSProvider
            from lyra.voice.providers.mock import MockSTTProvider, MockTTSProvider
            from lyra.voice.providers.elevenlabs import ElevenLabsTTSProvider

            capture = MicrophoneCapture.from_settings(settings)
            player = AudioPlayer()

            if settings.stt_provider == "mock":
                stt_provider: Any = MockSTTProvider()
            else:
                stt_provider = FreeSTTProvider()

            if settings.tts_provider == "mock":
                tts_provider: Any = MockTTSProvider()
            elif settings.tts_provider == "elevenlabs" and settings.elevenlabs_api_key:
                tts_provider = ElevenLabsTTSProvider(
                    api_key=settings.elevenlabs_api_key,
                    default_voice_id=settings.elevenlabs_voice_id,
                )
            else:
                tts_provider = SystemTTSProvider()

            conversation_mgr = VoiceConversationManager(
                orchestrator=orchestrator,
                session=session,
                capture=capture,
                stt_provider=stt_provider,
                tts_provider=tts_provider,
                player=player,
                settings=settings,
            )

            banner = [
                "========================================",
                "             LYRA",
                "      Personal AI Assistant",
                "========================================",
                "",
                "AI Providers:",
            ]
            for prov_name in ("gemini", "xai", "groq", "cerebras", "openrouter", "anakin", "local"):
                p = router.get_provider(prov_name)
                display_p = "Grok" if prov_name == "xai" else ("Anakin" if prov_name == "anakin" else ("OpenRouter" if prov_name == "openrouter" else ("Ollama" if prov_name == "local" else prov_name.capitalize())))
                if prov_name == "local":
                    status = router.tracker.get_status("local")
                    if status.value in ("AVAILABLE", "READY"):
                        banner.append(f"✓ {display_p} - online")
                    else:
                        banner.append(f"○ {display_p} - offline")
                elif p and p.is_configured:
                    banner.append(f"✓ {display_p} - configured")
                else:
                    banner.append(f"○ {display_p} - not configured")

            banner.extend([
                "",
                "Voice:",
                "✓ STT",
                "✓ TTS",
                "",
                "Tools:",
                "✓ Browser",
                "✓ Filesystem",
                "✓ macOS Controls",
                "✓ Anakin Workflows",
                "",
            ])
            print("Starting LYRA Voice Mode...\n")
            print("\n".join(banner))
            try:
                asyncio.run(conversation_mgr.run())
            except KeyboardInterrupt:
                print("\nVoice session closed. Goodbye!")
            return 0

        # Single prompt execution if arguments passed
        if args:
            parts: list[Any] = []
            prompt_words: list[str] = []
            i = 0
            while i < len(args):
                arg = args[i]
                if arg in ("--image", "-i") and i + 1 < len(args):
                    from lyra.models.multimodal import ImagePart
                    parts.append(ImagePart.from_file(args[i + 1]))
                    i += 2
                elif arg in ("--file", "-f") and i + 1 < len(args):
                    from lyra.models.multimodal import FilePart
                    parts.append(FilePart.from_file(args[i + 1]))
                    i += 2
                else:
                    prompt_words.append(arg)
                    i += 1

            prompt = " ".join(prompt_words).strip()
            if not prompt and parts:
                prompt = "Please inspect and summarize the attached content."

            if prompt:
                print(f"You: {prompt}\n")
                _stream_and_display(orchestrator, session, prompt, parts=parts)
                return 0

        # Interactive conversation loop
        print("(Type 'exit' or 'quit' to end the session. Commands: /login, /register, /whoami, /logout, /export, /schedule)\n")
        while True:
            try:
                user_input = input("You: ")
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            stripped = user_input.strip()
            if not stripped:
                continue

            if stripped.lower() in ("exit", "quit", "q"):
                print("\nGoodbye!")
                break

            # Slash commands for identity and auth
            if stripped.startswith("/"):
                cmd_parts = stripped.split(maxsplit=1)
                cmd = cmd_parts[0].lower()
                cmd_arg = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""

                if cmd == "/whoami":
                    if session.is_authenticated:
                        print(f"Authenticated as: {session.metadata.get('username')} (Display: {session.metadata.get('display_name')}, ID: {session.user_id})")
                    else:
                        print("Current state: Anonymous (ID: default_user)")
                    print()
                    continue

                if cmd == "/register":
                    username = cmd_arg
                    if not username:
                        try:
                            username = input("Enter username: ").strip()
                        except (EOFError, KeyboardInterrupt):
                            print()
                            continue
                    try:
                        pw = getpass.getpass("Enter password: ")
                    except Exception:
                        pw = input("Enter password: ")

                    display_name = input("Enter display name (optional): ").strip() or None
                    try:
                        user = auth_manager.register(
                            username=username,
                            password=pw,
                            display_name=display_name,
                        )
                        logged_user, token = auth_manager.login(username=username, password=pw)
                        session.bind_user(logged_user, token)
                        print(f"Successfully registered and logged in as '{user.username}'.\n")
                    except Exception as err:
                        print(f"Registration error: {err}\n")
                    continue

                if cmd == "/login":
                    username = cmd_arg
                    if not username:
                        try:
                            username = input("Enter username: ").strip()
                        except (EOFError, KeyboardInterrupt):
                            print()
                            continue
                    try:
                        pw = getpass.getpass("Enter password: ")
                    except Exception:
                        pw = input("Enter password: ")

                    try:
                        logged_user, token = auth_manager.login(username=username, password=pw)
                        session.bind_user(logged_user, token)
                        print(f"Logged in as '{logged_user.username}'.\n")
                    except Exception as err:
                        print(f"Login error: {err}\n")
                    continue

                if cmd == "/logout":
                    if session.auth_token:
                        auth_manager.logout(session.auth_token)
                    session.logout()
                    print("Logged out. Session reverted to anonymous.\n")
                    continue

                if cmd == "/export":
                    if not session.is_authenticated:
                        print("Cannot export: You are not logged in. Use /login first.\n")
                        continue
                    try:
                        data = auth_manager.export_user_data(session.user_id)
                        print(json.dumps(data, indent=2))
                    except Exception as err:
                        print(f"Export error: {err}")
                    print()
                    continue

                if cmd == "/delete-account":
                    if not session.is_authenticated:
                        print("Cannot delete account: You are not logged in.\n")
                        continue
                    confirm = input("Are you sure you want to permanently delete your account and all memories? (yes/no): ").strip().lower()
                    if confirm in ("yes", "y"):
                        try:
                            auth_manager.delete_user_data(session.user_id)
                            session.logout()
                            print("Your account and all associated data have been permanently deleted.\n")
                        except Exception as err:
                            print(f"Delete account error: {err}\n")
                    else:
                        print("Account deletion cancelled.\n")
                    continue

                if cmd in ("/schedule", "/automations"):
                    subparts = cmd_arg.split(maxsplit=2)
                    subcmd = subparts[0].lower() if subparts else "list"

                    if subcmd in ("list", ""):
                        autos = scheduler.list_automations(user_id=session.user_id)
                        if not autos:
                            print("No automations scheduled for this user.\n")
                        else:
                            print(f"Scheduled Automations ({len(autos)}):")
                            for a in autos:
                                status = "ENABLED" if a.enabled else "DISABLED"
                                nr = a.next_run.isoformat() if a.next_run else "None"
                                print(f"- [{a.id[:8]}] {a.name} ({a.trigger.type.value} -> {a.action.type.value}) - Status: {status}, Next: {nr}, Failures: {a.consecutive_failures}")
                            print()
                        continue

                    if subcmd == "create" and len(subparts) >= 3:
                        try:
                            delay_secs = float(subparts[1])
                            msg = subparts[2].strip()
                            run_at = datetime.now(timezone.utc) + timedelta(seconds=delay_secs)
                            auto = scheduler.create_automation(
                                user_id=session.user_id,
                                name=f"Reminder: {msg[:20]}",
                                trigger=OneTimeTrigger(run_at=run_at),
                                action=ReminderAction(message=msg),
                            )
                            print(f"Created one-time automation [{auto.id[:8]}] running in {delay_secs}s.\n")
                        except Exception as err:
                            print(f"Failed to create automation: {err}\n")
                        continue

                    if subcmd == "recurring" and len(subparts) >= 3:
                        try:
                            interval_secs = float(subparts[1])
                            msg = subparts[2].strip()
                            auto = scheduler.create_automation(
                                user_id=session.user_id,
                                name=f"Recurring: {msg[:20]}",
                                trigger=IntervalTrigger(interval_seconds=interval_secs),
                                action=ReminderAction(message=msg),
                            )
                            print(f"Created recurring automation [{auto.id[:8]}] every {interval_secs}s.\n")
                        except Exception as err:
                            print(f"Failed to create automation: {err}\n")
                        continue

                    if subcmd == "toggle" and len(subparts) >= 2:
                        target_id = subparts[1].strip()
                        autos = scheduler.list_automations(user_id=session.user_id)
                        matched = next((a for a in autos if a.id == target_id or a.id.startswith(target_id)), None)
                        if not matched:
                            print(f"Automation '{target_id}' not found.\n")
                        else:
                            if matched.enabled:
                                updated = scheduler.disable_automation(matched.id, user_id=session.user_id)
                                print(f"Disabled automation [{updated.id[:8]}].\n")
                            else:
                                updated = scheduler.enable_automation(matched.id, user_id=session.user_id)
                                print(f"Enabled automation [{updated.id[:8]}].\n")
                        continue

                    if subcmd == "delete" and len(subparts) >= 2:
                        target_id = subparts[1].strip()
                        autos = scheduler.list_automations(user_id=session.user_id)
                        matched = next((a for a in autos if a.id == target_id or a.id.startswith(target_id)), None)
                        if not matched:
                            print(f"Automation '{target_id}' not found.\n")
                        else:
                            scheduler.delete_automation(matched.id, user_id=session.user_id)
                            print(f"Deleted automation [{matched.id[:8]}].\n")
                        continue

                    print("Usage: /schedule [list | create <secs> <msg> | recurring <secs> <msg> | toggle <id> | delete <id>]\n")
                    continue

            print()
            _stream_and_display(orchestrator, session, stripped)
            print()

        return 0

    except ConfigurationError as err:
        sys.stderr.write(f"LYRA Configuration Error: {err}\n")
        return 1
    except LYRAError as err:
        sys.stderr.write(f"LYRA Runtime Error: {err}\n")
        return 1
    except Exception as err:  # pylint: disable=broad-except
        sys.stderr.write(f"Unexpected Fatal Error: {err}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
