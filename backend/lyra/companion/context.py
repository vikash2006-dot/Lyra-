"""Immediate conversation context preparation for LYRA."""

from typing import Any

from lyra.companion.personality import PersonalityProfile
from lyra.companion.session import Session
from lyra.models.messages import AIRequest, Message, Role


class ConversationContext:
    """Prepares and bounds immediate conversational context for AI generation.

    Maintains separation between short-term dialogue context and future
    persistent memory systems.
    """

    def __init__(
        self,
        personality: PersonalityProfile | None = None,
        max_context_messages: int = 50,
    ) -> None:
        self.personality: PersonalityProfile = personality or PersonalityProfile()
        self.max_context_messages: int = max_context_messages

    def build_request(
        self,
        session: Session,
        user_message: str | Message,
        temperature: float | None = None,
        max_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
        memory_context: str | None = None,
    ) -> AIRequest:
        """Construct a canonical AIRequest from session history and current message."""
        # Normalize new message
        if isinstance(user_message, str):
            current_msg = Message(role=Role.USER, content=user_message)
        elif isinstance(user_message, Message):
            current_msg = user_message
        else:
            raise ValueError(f"user_message must be a str or Message (got {type(user_message)})")

        # Gather bounded recent history (excluding the current user message if already added)
        history = list(session.get_history(limit=self.max_context_messages))

        # If current_msg is not already the last item in session, append it to the request list
        if not history or history[-1] != current_msg:
            combined_messages = history + [current_msg]
        else:
            combined_messages = history

        # System prompt from centralized personality
        system_prompt = self.personality.build_system_prompt()
        if memory_context and memory_context.strip():
            system_prompt = f"{system_prompt}\n\n{memory_context.strip()}"

        req_metadata = dict(metadata) if metadata else {}
        req_metadata["session_id"] = session.session_id

        return AIRequest(
            messages=combined_messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata=req_metadata,
        )
