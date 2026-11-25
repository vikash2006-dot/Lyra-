"""Base abstraction for AI providers in LYRA."""

from abc import ABC, abstractmethod
import asyncio
from collections.abc import AsyncIterator

from lyra.models.messages import AIRequest, AIResponse


class AIProvider(ABC):
    """Abstract base class for all LYRA AI providers.

    All concrete provider adapters (e.g., Gemini, Groq, Cerebras, OpenRouter)
    must inherit from this class and implement the required methods.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for the provider (e.g., 'gemini', 'groq', 'mock')."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """True if the provider has all required credentials and settings to operate."""

    @property
    def status(self) -> str:
        """Human-readable status of the provider ('READY' or 'NOT_CONFIGURED')."""
        return "READY" if self.is_configured else "NOT_CONFIGURED"

    @property
    def supports_vision(self) -> bool:
        """Whether this provider can process image inputs."""
        return False

    @property
    def supports_audio(self) -> bool:
        """Whether this provider can process audio inputs."""
        return False

    @property
    def supports_files(self) -> bool:
        """Whether this provider can process document/file attachments."""
        return False

    @property
    def supports_streaming(self) -> bool:
        """Whether this provider supports token streaming."""
        return False

    @property
    def capabilities(self) -> frozenset[Any]:
        """Declared capabilities supported by this provider."""
        from lyra.models.capabilities import ProviderCapability

        caps: set[ProviderCapability] = {ProviderCapability.TEXT_GENERATION}
        if self.supports_streaming:
            caps.add(ProviderCapability.STREAMING)
        if self.supports_vision:
            caps.add(ProviderCapability.IMAGE_UNDERSTANDING)
        if self.supports_files:
            caps.add(ProviderCapability.DOCUMENT_UNDERSTANDING)
        if self.supports_audio:
            caps.add(ProviderCapability.AUDIO_UNDERSTANDING)
        return frozenset(caps)

    def has_capability(self, capability: Any) -> bool:
        """Check if this provider supports a specific capability."""
        return capability in self.capabilities

    async def stream_events(
        self,
        request: AIRequest,
        cancellation_token: Any | None = None,
    ) -> AsyncIterator[Any]:
        """Stream typed StreamEvents (StreamStarted, TextDelta, StreamCompleted, StreamError)."""
        from lyra.core.exceptions import StreamInterruptedError, UnsupportedCapabilityError
        from lyra.models.capabilities import ProviderCapability
        from lyra.models.stream import StreamCompleted, StreamError, StreamStarted, TextDelta

        if not self.has_capability(ProviderCapability.STREAMING):
            raise UnsupportedCapabilityError(
                f"Provider '{self.name}' does not support capability '{ProviderCapability.STREAMING.value}'."
            )

        model = request.model or getattr(self, "_default_model", self.name)
        yield StreamStarted(provider=self.name, model=model)

        accumulated: list[str] = []
        idx = 0
        try:
            async for token in self.stream(request):
                if cancellation_token and cancellation_token.is_cancelled:
                    raise StreamInterruptedError(cancellation_token.reason or "Stream cancelled by user.")
                accumulated.append(token)
                yield TextDelta(delta=token, index=idx)
                idx += 1

            yield StreamCompleted(full_text="".join(accumulated))

        except Exception as err:
            yield StreamError(error_message=str(err), recoverable=False)
            raise

    @abstractmethod
    async def generate(self, request: AIRequest) -> AIResponse:
        """Generate an AI response asynchronously for the given request.

        Args:
            request: The validated, provider-agnostic request.

        Returns:
            AIResponse containing the model's generated output.

        Raises:
            ProviderError: If the provider encounters a runtime, network, or service failure.
            ModelValidationError: If the request or response is invalid.
        """

    def generate_sync(self, request: AIRequest) -> AIResponse:
        """Synchronously execute generate() by running the event loop.

        Args:
            request: The validated, provider-agnostic request.

        Returns:
            AIResponse from the provider.
        """
        return asyncio.run(self.generate(request))

    async def stream(self, request: AIRequest) -> AsyncIterator[str]:
        """Stream response tokens asynchronously (future extension hook).

        Args:
            request: The validated, provider-agnostic request.

        Raises:
            NotImplementedError: If the provider does not support streaming.
        """
        raise NotImplementedError(f"Streaming is not supported by provider '{self.name}'.")
        # Ensure Python treats this as an async generator
        yield ""  # pragma: no cover

    async def health_check(self) -> bool:
        """Verify provider availability and configuration status.

        Returns:
            bool: True if the provider is configured and available.
        """
        return self.is_configured
