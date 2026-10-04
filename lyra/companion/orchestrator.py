"""Conversational turn orchestrator for LYRA."""

import asyncio
from typing import Any

from lyra.companion.context import ConversationContext
from lyra.companion.personality import PersonalityProfile
from lyra.companion.planner import ActionPlanner, TaskPlan
from lyra.companion.session import Session
from lyra.core.exceptions import (
    ModelValidationError,
    NoAvailableProviderError,
    ProviderError,
)
from lyra.memory.manager import MemoryManager
from lyra.models.messages import AIRequest, AIResponse
from lyra.models.tools import ToolRequest
from lyra.observability.logging import get_logger, sanitize_text
from lyra.routing.router import ModelRouter
from lyra.tools.decider import ToolDecider
from lyra.tools.executor import ToolExecutor
from lyra.tools.registry import ToolRegistry
from lyra.tools.sanitizer import wrap_untrusted_context

UNCONFIGURED_ASSISTANCE_MESSAGE = (
    "I am currently running without any configured AI providers. "
    "To enable conversational intelligence, please add a free provider API key "
    "(such as GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, or CEREBRAS_API_KEY) "
    "to your .env file or environment."
)


class CompanionOrchestrator:
    """Orchestrates conversational turns between user input, tools, context, router, and session."""

    def __init__(
        self,
        router: ModelRouter,
        context: ConversationContext | None = None,
        personality: PersonalityProfile | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
        memory_manager: MemoryManager | None = None,
        offline_mode: bool | None = None,
        capability_registry: Any | None = None,
        learning_service: Any | None = None,
    ) -> None:
        self.router: ModelRouter = router
        self.personality: PersonalityProfile = personality or PersonalityProfile()
        self.context: ConversationContext = context or ConversationContext(personality=self.personality)
        self.tool_registry: ToolRegistry | None = tool_registry
        self.tool_executor: ToolExecutor | None = tool_executor
        from lyra.core.capabilities import CapabilityRegistry
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.tool_decider: ToolDecider | None = (
            ToolDecider(tool_registry) if tool_registry is not None else None
        )
        self.memory_manager: MemoryManager | None = memory_manager
        self.learning_service = learning_service
        self.planner: ActionPlanner = ActionPlanner(
            tool_registry=self.tool_registry,
            router=self.router,
            capability_registry=self.capability_registry,
        )
        self._offline_mode: bool = (
            offline_mode if offline_mode is not None else getattr(self.router, "offline_mode", False)
        )
        self._logger = get_logger("orchestrator")

    @property
    def offline_mode(self) -> bool:
        return self._offline_mode

    @offline_mode.setter
    def offline_mode(self, value: bool) -> None:
        self._offline_mode = value
        if hasattr(self.router, "offline_mode"):
            self.router.offline_mode = value
        if self.tool_executor and hasattr(self.tool_executor, "offline_mode"):
            self.tool_executor.offline_mode = value

    # 1. Input handling
    def handle_input(self, raw_input: str) -> str:
        """Validate and sanitize user input text."""
        if not isinstance(raw_input, str):
            raise ModelValidationError(f"Expected string input, got {type(raw_input).__name__}")
        clean_input = raw_input.strip()
        if not clean_input:
            raise ModelValidationError("User input cannot be empty or whitespace.")
        return clean_input

    # 2. Tool decision
    def decide_tool(
        self,
        clean_input: str,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> ToolRequest | None:
        """Determine if user input requires invoking a registered tool."""
        if not self.tool_decider:
            return None
        req = self.tool_decider.decide(clean_input, session_id=session_id)
        if req and user_id:
            return ToolRequest(
                tool_name=req.tool_name,
                arguments=req.arguments,
                session_id=req.session_id,
                user_id=user_id,
                metadata=req.metadata,
            )
        return req

    # 3. Context preparation
    def prepare_context(
        self,
        session: Session,
        clean_input: str,
        parts: Sequence[Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AIRequest:
        """Assemble session history, personality system instructions, memory context, and new user message."""
        if parts:
            from lyra.models.messages import Message, Role
            msg = Message(role=Role.USER, content=clean_input, parts=tuple(parts))
            session.add_message(msg)
        else:
            session.add_user_message(clean_input)

        memory_context = (
            self.memory_manager.get_context_summary(session.user_id)
            if self.memory_manager
            else None
        )
        if self.learning_service and session.user_id:
            try:
                prof = self.learning_service.get_profile(session.user_id)
                if prof and prof.target_role:
                    active_plan = self.learning_service.get_active_plan(session.user_id)
                    cur_obj = active_plan.objectives[0] if active_plan and active_plan.objectives else "Active"
                    learn_summary = f"[Learner Profile: Target Role: {prof.target_role}, Hours: {prof.weekly_learning_hours}h/wk, Focus: {cur_obj}, Weaknesses: {', '.join(prof.weak_topics) or 'None'}]"
                    memory_context = f"{memory_context}\n\n{learn_summary}" if memory_context else learn_summary
            except Exception:
                pass
        meta = dict(metadata or {})
        if self._offline_mode:
            meta["offline_mode"] = True

        # Build canonical AIRequest
        return self.context.build_request(
            session=session,
            user_message=clean_input,
            metadata=meta,
            memory_context=memory_context,
        )

    # 4. Provider selection & generation
    async def execute_generation(self, request: AIRequest) -> AIResponse:
        """Dispatch request to the ModelRouter for provider selection and execution."""
        return await self.router.route(request)

    # 5. Response handling
    def handle_response(self, session: Session, response: AIResponse) -> str:
        """Record the model response into the session and return the text content."""
        session.add_assistant_message(
            content=response.content,
            model=response.model,
            metadata={"finish_reason": response.finish_reason} if response.finish_reason else None,
        )
        return response.content

    async def _execute_plan_turn(
        self,
        plan: TaskPlan,
        session: Session,
        clean_input: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Execute a structured TaskPlan, verify all tool results, and synthesize a truthful response."""
        session.add_user_message(clean_input)

        if plan.intent == "cancel_action":
            reply = "Action cancelled."
            session.add_assistant_message(reply)
            return reply

        if plan.user_confirmation_prompt:
            reply = plan.user_confirmation_prompt
            session.add_assistant_message(reply)
            return reply

        results: list[Any] = []
        if self.tool_executor:
            for step in plan.steps:
                req = step.to_tool_request(session_id=session.session_id, user_id=session.user_id)
                self._logger.info("Executing plan step '%s' with arguments %s", step.tool, step.arguments)
                res = await self.tool_executor.execute(req)
                results.append(res)
                if not res.success:
                    self._logger.warning("Plan step '%s' failed: %s", step.tool, res.error)
                    break

        if not results:
            reply = "No actions were executed."
            session.add_assistant_message(reply)
            return reply

        # Construct deterministic truthful fallback reply
        if plan.intent == "notes_write":
            text = next((s.arguments.get("text") for s in plan.steps if s.arguments.get("text")), "message")
            if all(r.is_success() for r in results):
                fallback_reply = f"Done, I wrote '{text}' in Notes."
            else:
                failed = next(r for r in results if not r.is_success())
                fallback_reply = f"Notes is open, but I couldn't type the message: {failed.error}"
        elif plan.intent == "open_notes":
            if all(r.is_success() for r in results):
                fallback_reply = "Done, Notes is open."
            else:
                failed = next(r for r in results if not r.is_success())
                fallback_reply = f"Could not open Notes: {failed.error}"
        elif plan.intent == "create_folder_structure":
            if all(r.is_success() for r in results):
                last_res = results[-1]
                count = last_res.output.get("count", 0) if isinstance(last_res.output, dict) else len(results)
                root_name = last_res.output.get("root_name") if isinstance(last_res.output, dict) else None
                if root_name:
                    fallback_reply = f"Done, I created the {root_name} folder structure with {count} directories on your Desktop."
                else:
                    fallback_reply = f"Done, I created the requested structure with {count} directories on your Desktop."
            else:
                failed = next(r for r in results if not r.is_success())
                fallback_reply = f"Failed to create folder structure: {failed.error}"
        elif plan.intent in ("open_vscode_project", "open_file_in_vscode"):
            if all(r.is_success() for r in results):
                fallback_reply = "Done, I opened VS Code."
            else:
                failed = next(r for r in results if not r.is_success())
                fallback_reply = f"Could not open VS Code: {failed.error}"
        elif plan.intent == "create_folder_and_file":
            f_name = next(
                (r.output.get("name") for r in results if isinstance(r.output, dict) and r.output.get("action") == "create_directory"),
                "folder",
            )
            file_name = next(
                (r.output.get("name") for r in results if isinstance(r.output, dict) and r.output.get("action") == "create_file"),
                "file",
            )
            if all(r.is_success() for r in results):
                fallback_reply = f"Done, I created {f_name} on your Desktop and created {file_name} inside it."
            else:
                failed = next(r for r in results if not r.is_success())
                fallback_reply = f"I couldn't complete the task: {failed.error}"
        elif plan.intent == "youtube_search_and_play":
            query = plan.steps[0].arguments.get("query", "music")
            if all(r.is_success() for r in results):
                fallback_reply = f"Done. {query} is playing."
            else:
                failed = next(r for r in results if not r.is_success())
                fallback_reply = f"I couldn't play YouTube media: {failed.error}"
        elif plan.intent == "google_search_and_open":
            query = plan.steps[0].arguments.get("query", "topic")
            if all(r.is_success() for r in results):
                fallback_reply = f"Searched Google for '{query}' and opened the first result."
            else:
                failed = next(r for r in results if not r.is_success())
                fallback_reply = f"Search failed: {failed.error}"
        elif plan.intent == "chrome_tab_search_and_open":
            query = next((s.arguments.get("query") for s in plan.steps if "query" in s.arguments), "search")
            if all(r.is_success() for r in results):
                fallback_reply = f"Opened Chrome, created a new tab, searched Google for '{query}', and opened the first result."
            else:
                failed = next(r for r in results if not r.is_success())
                fallback_reply = f"I couldn't complete the task: {failed.error}"
        elif plan.intent == "new_tab_google_search":
            if all(r.is_success() for r in results):
                fallback_reply = "Opened a new tab and searched Google."
            else:
                failed = next(r for r in results if not r.is_success())
                fallback_reply = f"Failed to search in new tab: {failed.error}"
        elif plan.intent == "new_tab_youtube_search":
            if all(r.is_success() for r in results):
                fallback_reply = "Opened a new tab and searched YouTube."
            else:
                failed = next(r for r in results if not r.is_success())
                fallback_reply = f"Failed to search in new tab: {failed.error}"
        elif all(r.is_success() for r in results):
            last_res = results[-1]
            tool = self.tool_registry.get(last_res.tool_name) if self.tool_registry else None
            fallback_reply = tool.format_result(last_res) if tool and hasattr(tool, "format_result") else "Done, I have completed the requested task."
        else:
            failed = next(r for r in results if not r.is_success())
            if failed.metadata.get("requires_confirmation"):
                fallback_reply = failed.error or "Confirmation required before executing this action."
            else:
                fallback_reply = f"I couldn't complete the action: {failed.error}"

        # Observability / Debug Mode
        import os, sys
        if os.environ.get("LYRA_DEBUG", "").lower() in ("true", "1", "yes"):
            sys.stdout.write(f"\n[DEBUG] Intent: {plan.intent}\n")
            sys.stdout.write(f"[DEBUG] Plan Steps ({len(plan.steps)}):\n")
            for idx, s in enumerate(plan.steps, 1):
                sys.stdout.write(f"  {idx}. {s.description or s.tool}\n")
            sys.stdout.write(f"[DEBUG] Execution Results:\n")
            for r in results:
                icon = "✓" if r.is_success() else "✗"
                sys.stdout.write(f"  {icon} {r.tool_name}: {r.to_text()[:120]}\n")
            sys.stdout.flush()

        # If an AI provider (e.g. Gemini, Groq) is configured and not in offline mode, synthesize truthful response
        has_configured = any(p.is_configured for p in self.router.list_providers())
        if has_configured and not self._offline_mode:
            contained_output = "\n---\n".join(
                wrap_untrusted_context(source=r.tool_name, content=r.to_text())
                for r in results
            )
            augmented_prompt = (
                f"User asked: {clean_input}\n\n"
                f"Real Action Execution Results:\n{contained_output}\n\n"
                "INSTRUCTIONS:\n"
                "1. Confirm directly to the user what was actually performed based on the execution results above.\n"
                "2. Be extremely concise and natural in one short sentence (e.g. 'Done, I created the Projects folder on your Desktop.').\n"
                "3. Do NOT provide instructions on how to do the action manually (e.g. do not say 'You can use mkdir...').\n"
                "4. Never claim an action succeeded if it failed.\n"
                "5. If an action required confirmation, ask for confirmation clearly."
            )
            req_metadata = dict(metadata or {})
            req_metadata["task_results"] = [r.output for r in results]
            memory_context = (
                self.memory_manager.get_context_summary(session.user_id)
                if self.memory_manager
                else None
            )
            request = self.context.build_request(
                session=session,
                user_message=augmented_prompt,
                metadata=req_metadata,
                memory_context=memory_context,
            )
            try:
                response = await self.execute_generation(request)
                reply = self.handle_response(session=session, response=response)
                return reply
            except Exception as gen_err:
                self._logger.warning("AI synthesis of task results failed: %s. Using deterministic response.", gen_err)

        session.add_assistant_message(
            content=fallback_reply,
            metadata={"task_intent": plan.intent, "steps_executed": len(results)},
        )
        return fallback_reply

    async def process_turn(
        self,
        session: Session,
        raw_user_input: str,
        parts: Sequence[Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Execute a full conversational turn through the modular pipeline.

        Pipeline:
            User Input -> Action Plan (if actionable) -> Tool Execution -> Verification -> Response Synthesis
        """
        # Step 1: Input handling
        try:
            clean_input = self.handle_input(raw_user_input)
        except ModelValidationError as val_err:
            self._logger.warning("Invalid input received: %s", val_err)
            return f"Input Error: {val_err}"

        # Step 2a: Check ActionPlanner for task planning & real action execution
        if not parts and self.tool_executor and self.tool_registry:
            plan = self.planner.plan(clean_input, session=session)
            if not plan and hasattr(self.planner, "plan_async"):
                try:
                    plan = await self.planner.plan_async(clean_input, session=session)
                except Exception as plan_err:
                    self._logger.debug("LLM action planning failed: %s", plan_err)
            if plan:
                self._logger.info("Task plan generated: intent='%s', steps=%d", plan.intent, len(plan.steps))
                reply = await self._execute_plan_turn(plan, session, clean_input, metadata=metadata)
                return reply

        # Step 2b: Tool decision & execution (if applicable and no media attachments)
        tool_request = (
            self.decide_tool(clean_input, session_id=session.session_id, user_id=session.user_id)
            if not parts
            else None
        )
        if tool_request and self.tool_executor and self.tool_registry:
            self._logger.info("Tool decision made: '%s'", tool_request.tool_name)
            tool_result = await self.tool_executor.execute(tool_request)

            # Record user query in session history
            session.add_user_message(clean_input)

            # For action tools (system, filesystem, browser, computer, media, keyboard, mouse),
            # return deterministic short natural confirmation directly without redundant LLM call
            action_tools = {"system", "filesystem", "browser", "computer", "media", "keyboard", "mouse"}
            if tool_result.tool_name in action_tools:
                tool = self.tool_registry.get(tool_result.tool_name)
                reply = tool.format_result(tool_result) if tool and hasattr(tool, "format_result") else tool_result.to_text()
                session.add_assistant_message(
                    content=reply,
                    metadata={"tool_name": tool_result.tool_name, "tool_success": tool_result.success},
                )
                return reply

            # Check if an AI provider is configured for informational tool response synthesis (weather, news, etc.)
            has_configured = any(p.is_configured for p in self.router.list_providers())
            if has_configured:
                contained_output = wrap_untrusted_context(
                    source=tool_result.tool_name,
                    content=tool_result.to_text(),
                )
                augmented_prompt = (
                    f"User asked: {clean_input}\n\n"
                    f"{contained_output}\n\n"
                    "Respond to the user naturally, accurately, and concisely incorporating the factual data from the tool result."
                )
                req_metadata = dict(metadata or {})
                req_metadata["tool_result"] = tool_result.output
                memory_context = (
                    self.memory_manager.get_context_summary(session.user_id)
                    if self.memory_manager
                    else None
                )
                request = self.context.build_request(
                    session=session,
                    user_message=augmented_prompt,
                    metadata=req_metadata,
                    memory_context=memory_context,
                )
                try:
                    response = await self.execute_generation(request)
                    return self.handle_response(session=session, response=response)
                except Exception as gen_err:
                    self._logger.warning(
                        "AI synthesis of tool result failed: %s. Falling back to direct tool format.",
                        gen_err,
                    )

            # Fallback or offline presentation
            tool = self.tool_registry.get(tool_result.tool_name)
            if tool and hasattr(tool, "format_result"):
                reply = tool.format_result(tool_result)
            else:
                reply = tool_result.to_text()

            session.add_assistant_message(
                content=reply,
                metadata={
                    "tool_name": tool_result.tool_name,
                    "tool_success": tool_result.success,
                },
            )
            return reply

        # Step 3: Standard conversational turn Context preparation
        request = self.prepare_context(session=session, clean_input=clean_input, parts=parts, metadata=metadata)

        # Step 4: Provider selection & generation
        try:
            response = await self.execute_generation(request)
        except NoAvailableProviderError as no_prov_err:
            if self._offline_mode:
                error_msg = (
                    "LYRA is currently operating in [OFFLINE MODE]. No local AI model runtime (such as Ollama) was found or responding. "
                    "External cloud AI providers are strictly disabled to protect your privacy. "
                    "Please ensure your local runtime is running, or disable offline mode."
                )
                self._logger.warning("Offline mode AI generation unavailable: %s", no_prov_err)
                session.add_assistant_message(error_msg)
                return error_msg

            has_configured = any(p.is_configured for p in self.router.list_providers())
            if not has_configured:
                self._logger.warning("No providers configured in router pool.")
                session.add_assistant_message(UNCONFIGURED_ASSISTANCE_MESSAGE)
                return UNCONFIGURED_ASSISTANCE_MESSAGE

            self._logger.error("All configured candidate providers failed: %s", sanitize_text(str(no_prov_err)))
            tracker = getattr(self.router, "_tracker", None)
            gemini_quota_exhausted = False
            if tracker:
                from lyra.routing.health import ProviderHealthStatus
                gemini_quota_exhausted = tracker.get_status("gemini") == ProviderHealthStatus.QUOTA_EXHAUSTED
            configured = [p for p in self.router.list_providers() if p.is_configured]
            fallback_configured = [p for p in configured if p.name != "gemini"]

            if gemini_quota_exhausted and not fallback_configured:
                error_msg = (
                    "I don't currently have an available AI provider: "
                    "Gemini quota is exhausted and no fallback AI provider is configured. "
                    "Please configure a fallback provider such as GROQ_API_KEY or XAI_API_KEY in your .env file."
                )
            else:
                error_msg = (
                    "I don't currently have an available AI provider. "
                    "All candidate providers are currently unavailable, offline, or have exceeded their quota."
                )
            session.add_assistant_message(error_msg)
            return error_msg
        except ProviderError as prov_err:
            clean_err = sanitize_text(str(prov_err))
            self._logger.error("Provider execution error: %s", clean_err)
            error_msg = "I encountered an error communicating with the AI service. Please try again shortly."
            session.add_assistant_message(error_msg)
            return error_msg
        except Exception as err:  # pylint: disable=broad-except
            clean_err = sanitize_text(str(err))
            self._logger.error("Unexpected error in process_turn: %s", clean_err)
            error_msg = "An unexpected error occurred. Please try again."
            session.add_assistant_message(error_msg)
            return error_msg

        # Step 5: Response handling
        return self.handle_response(session=session, response=response)

    def process_turn_sync(
        self,
        session: Session,
        raw_user_input: str,
        parts: Sequence[Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Synchronously process a conversational turn."""
        return asyncio.run(self.process_turn(session, raw_user_input, parts=parts, metadata=metadata))

    async def stream_turn(
        self,
        session: Session,
        raw_user_input: str,
        parts: Sequence[Any] | None = None,
        metadata: dict[str, Any] | None = None,
        cancellation_token: Any | None = None,
    ):
        """Stream a conversational turn emitting typed StreamEvents."""
        from lyra.models.stream import StreamCompleted, StreamError, StreamStarted, TextDelta

        try:
            clean_input = self.handle_input(raw_user_input)
        except ModelValidationError as val_err:
            self._logger.warning("Invalid input received: %s", val_err)
            err_text = f"Input Error: {val_err}"
            yield StreamStarted(provider="system", model="input_validation")
            yield TextDelta(delta=err_text, index=0)
            yield StreamCompleted(full_text=err_text)
            return

        # Check for action plan if no media attachments
        if not parts and self.tool_executor and self.tool_registry:
            plan = self.planner.plan(clean_input, session=session)
            if not plan and hasattr(self.planner, "plan_async"):
                try:
                    plan = await self.planner.plan_async(clean_input, session=session)
                except Exception as plan_err:
                    self._logger.debug("LLM streaming action planning failed: %s", plan_err)
            if plan:
                self._logger.info("Task plan streaming: intent='%s', steps=%d", plan.intent, len(plan.steps))
                reply = await self._execute_plan_turn(plan, session, clean_input, metadata=metadata)
                yield StreamStarted(provider="action_planner", model=plan.intent)
                yield TextDelta(delta=reply, index=0)
                yield StreamCompleted(full_text=reply)
                return

        # Check for tool call if no media attachments
        if not parts:
            tool_request = self.decide_tool(clean_input, session_id=session.session_id, user_id=session.user_id)
            if tool_request and self.tool_executor and self.tool_registry:
                tool_result = await self.tool_executor.execute(tool_request)
                session.add_user_message(clean_input)

                # For action tools, yield short natural confirmation directly
                action_tools = {"system", "filesystem", "browser", "computer", "media", "keyboard", "mouse"}
                if tool_result.tool_name in action_tools:
                    tool = self.tool_registry.get(tool_result.tool_name)
                    reply = tool.format_result(tool_result) if tool and hasattr(tool, "format_result") else tool_result.to_text()
                    session.add_assistant_message(reply)
                    yield StreamStarted(provider="tool_executor", model=tool_result.tool_name)
                    yield TextDelta(delta=reply, index=0)
                    yield StreamCompleted(full_text=reply)
                    return

                has_configured = any(p.is_configured for p in self.router.list_providers())
                if has_configured:
                    contained_output = wrap_untrusted_context(
                        source=tool_result.tool_name,
                        content=tool_result.to_text(),
                    )
                    augmented_prompt = (
                        f"User asked: {clean_input}\n\n"
                        f"{contained_output}\n\n"
                        "Respond to the user naturally, accurately, and concisely incorporating the factual data from the tool result."
                    )
                    req_metadata = dict(metadata or {})
                    req_metadata["tool_result"] = tool_result.output
                    memory_context = (
                        self.memory_manager.get_context_summary(session.user_id)
                        if self.memory_manager
                        else None
                    )
                    request = self.context.build_request(
                        session=session,
                        user_message=augmented_prompt,
                        metadata=req_metadata,
                        memory_context=memory_context,
                    )
                    accumulated = []
                    yielded_text = False
                    try:
                        async for event in self.router.stream_events(request, cancellation_token=cancellation_token):
                            if isinstance(event, TextDelta):
                                yielded_text = True
                                accumulated.append(event.delta)
                            yield event
                        if yielded_text:
                            session.add_assistant_message("".join(accumulated))
                            return
                        self._logger.warning(
                            "AI synthesis produced no text deltas. Falling back to direct tool format."
                        )
                    except Exception as gen_err:
                        self._logger.warning(
                            "AI synthesis of tool result failed: %s. Falling back to direct tool format.",
                            gen_err,
                        )
                        if yielded_text:
                            return

                # Offline presentation
                tool = self.tool_registry.get(tool_result.tool_name)
                reply = tool.format_result(tool_result) if tool and hasattr(tool, "format_result") else tool_result.to_text()
                session.add_assistant_message(reply)
                yield StreamStarted(provider="tool", model=tool_result.tool_name)
                yield TextDelta(delta=reply, index=0)
                yield StreamCompleted(full_text=reply)
                return

        # Standard context preparation
        request = self.prepare_context(session=session, clean_input=clean_input, parts=parts, metadata=metadata)

        has_configured = any(p.is_configured for p in self.router.list_providers())
        if not has_configured:
            session.add_assistant_message(UNCONFIGURED_ASSISTANCE_MESSAGE)
            yield StreamStarted(provider="system", model="unconfigured")
            yield TextDelta(delta=UNCONFIGURED_ASSISTANCE_MESSAGE, index=0)
            yield StreamCompleted(full_text=UNCONFIGURED_ASSISTANCE_MESSAGE)
            return

        accumulated = []
        try:
            async for event in self.router.stream_events(request, cancellation_token=cancellation_token):
                if isinstance(event, TextDelta):
                    accumulated.append(event.delta)
                yield event
            session.add_assistant_message("".join(accumulated))
        except Exception as err:
            clean_err = sanitize_text(str(err))
            self._logger.error("Error in stream_turn: %s", clean_err)
            tracker = getattr(self.router, "_tracker", None)
            gemini_quota_exhausted = False
            if tracker:
                from lyra.routing.health import ProviderHealthStatus
                gemini_quota_exhausted = tracker.get_status("gemini") == ProviderHealthStatus.QUOTA_EXHAUSTED
            configured = [p for p in self.router.list_providers() if p.is_configured]
            fallback_configured = [p for p in configured if p.name != "gemini"]

            if gemini_quota_exhausted and not fallback_configured:
                err_msg = "Gemini quota is exhausted and no fallback AI provider is configured."
            else:
                err_msg = "I don't currently have an available AI provider."
            session.add_assistant_message(err_msg)
            yield StreamError(error_message=err_msg, recoverable=False)

