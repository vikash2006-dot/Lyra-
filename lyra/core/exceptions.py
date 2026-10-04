"""Core exceptions for LYRA."""


class LYRAError(Exception):
    """Base exception class for all LYRA runtime errors."""


class ConfigurationError(LYRAError):
    """Raised when application configuration is missing, malformed, or invalid."""


class ProviderError(LYRAError):
    """Raised when an AI provider fails during an operation."""


class ProviderNotConfiguredError(ProviderError):
    """Raised when an operation is requested on an unconfigured AI provider."""


class ProviderAuthenticationError(ProviderError):
    """Raised when provider authentication fails (e.g. invalid or revoked API key)."""


class ProviderRateLimitError(ProviderError):
    """Raised when provider rate limits or quotas are exceeded."""


class ProviderQuotaExceededError(ProviderRateLimitError):
    """Raised specifically when a provider's free-tier or daily/monthly quota is exhausted."""


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request times out."""


class ProviderResponseError(ProviderError):
    """Raised when a provider returns an unparseable, incomplete, or malformed response."""


class ModelValidationError(LYRAError):
    """Raised when an internal message, request, or response model fails validation."""


class RoutingError(LYRAError):
    """Base exception class for model routing errors."""


class NoAvailableProviderError(RoutingError):
    """Raised when no configured AI provider is available or all candidates fail."""


class CompanionError(LYRAError):
    """Base exception class for companion operations."""


class SessionError(CompanionError):
    """Raised when session creation, lookup, or mutation fails."""


class ToolError(LYRAError):
    """Base exception class for tool operations."""


class ToolNotFoundError(ToolError):
    """Raised when a requested tool cannot be found in the registry."""


class ToolValidationError(ToolError):
    """Raised when tool input arguments fail schema validation."""


class ToolPermissionError(ToolError):
    """Raised when an operation violates tool permission policies."""


class ToolExecutionError(ToolError):
    """Raised when a tool encounters an error during execution."""


class ToolTimeoutError(ToolError):
    """Raised when tool execution exceeds the permitted time limit."""


class ToolLimitExceededError(ToolError):
    """Raised when the maximum number of tool executions in a single turn is exceeded."""


class ToolNetworkError(ToolExecutionError):
    """Raised when an external network request fails during tool execution."""


class ToolRateLimitError(ToolExecutionError):
    """Raised when an external tool hits upstream rate limits (HTTP 429)."""


class VoiceError(LYRAError):
    """Base exception for all voice processing operations."""


class VoiceNotConfiguredError(VoiceError):
    """Raised when a voice operation requires credentials that are not configured."""


class VoiceAuthenticationError(VoiceError):
    """Raised when voice provider authentication fails."""


class VoiceRateLimitError(VoiceError):
    """Raised when a voice provider rate limit is exceeded."""


class VoiceTimeoutError(VoiceError):
    """Raised when voice transcription or synthesis exceeds timeout limit."""


class VoiceInterruptedError(VoiceError):
    """Raised when active speech playback or streaming is interrupted/cancelled."""


class VoiceExecutionError(VoiceError):
    """Raised when speech synthesis, transcription, or audio processing fails."""


class STTTranscriptionError(VoiceExecutionError):
    """Raised when speech-to-text transcription fails."""


class AudioPlaybackError(VoiceExecutionError):
    """Raised when audio playback fails."""


class MicrophoneUnavailableError(VoiceError):
    """Raised when microphone device is missing, permission denied, or cannot be accessed."""


class SilenceTimeoutError(VoiceError):
    """Raised when no speech is detected within the silence listening window."""


class EmptyAudioError(VoiceError):
    """Raised when captured audio payload contains zero speech samples or is empty."""


class MemoryError(LYRAError):
    """Base exception for all memory operations."""


class MemoryNotFoundError(MemoryError):
    """Raised when a specific memory record is not found."""


class MemoryPolicyViolationError(MemoryError):
    """Raised when a memory candidate violates storage policy (privacy, sensitive data, low importance)."""


class MemoryStorageError(MemoryError):
    """Raised when the underlying memory repository encounters an error."""


class UnsupportedCapabilityError(ProviderError):
    """Raised when an operation requires a capability not supported by the selected provider."""


class StreamingError(ProviderError):
    """Base exception for streaming response generation errors."""


class StreamInterruptedError(StreamingError):
    """Raised when an active response stream is cancelled or interrupted."""


class AuthError(LYRAError):
    """Base exception for all authentication and identity operations."""


class AuthenticationFailedError(AuthError):
    """Raised when user authentication fails due to invalid credentials."""


class UserNotFoundError(AuthError):
    """Raised when a specified user identity is not found."""


class UserAlreadyExistsError(AuthError):
    """Raised when attempting to register a user with an already existing username."""


class AccountLockedError(AuthError):
    """Raised when an account is temporarily locked due to excessive failed attempts."""


class SessionExpiredError(AuthError):
    """Raised when an authenticated session or token has expired."""


class InvalidTokenError(AuthError):
    """Raised when an authentication token is malformed, revoked, or unrecognized."""


class PasswordValidationError(AuthError):
    """Raised when a password fails policy validation (e.g. length, complexity)."""


class AutomationError(LYRAError):
    """Base exception for all automation and scheduling operations."""


class AutomationNotFoundError(AutomationError):
    """Raised when a requested automation task is not found."""


class AutomationValidationError(AutomationError):
    """Raised when an automation, trigger, or action configuration fails validation."""


class AutomationExecutionError(AutomationError):
    """Raised when an automated action fails during execution."""


class AutomationScheduleError(AutomationError):
    """Raised when schedule calculation, parsing, or interval setting fails."""


class AutomationLimitExceededError(AutomationError):
    """Raised when user exceeds maximum allowed automations or retry limits."""


class BrowserError(LYRAError):
    """Base exception class for all browser automation operations."""


class BrowserPolicyViolationError(BrowserError):
    """Raised when a browser action violates security policy (domain, SSRF, scheme)."""


class BrowserConfirmationRequiredError(BrowserError):
    """Raised when a browser action requires explicit user confirmation."""


class BrowserDownloadLimitError(BrowserError):
    """Raised when a file download exceeds size or count limits."""


class BrowserNavigationError(BrowserError):
    """Raised when browser navigation fails or target page cannot be loaded."""


class BrowserTimeoutError(BrowserError, ToolTimeoutError):
    """Raised when a browser operation exceeds permitted timeout limit."""


class BrowserDriverError(BrowserError):
    """Raised when underlying browser driver fails or is unconfigured."""


class ComputerError(LYRAError):
    """Base exception class for controlled computer interaction operations."""


class ComputerDisabledError(ComputerError):
    """Raised when computer interaction is globally disabled by configuration."""


class ComputerPolicyViolationError(ComputerError):
    """Raised when an action violates computer security policy (blocked app, dangerous hotkey, bounds)."""


class ComputerConfirmationRequiredError(ComputerError):
    """Raised when a consequential computer action requires explicit user confirmation."""


class ComputerEmergencyStopError(ComputerError):
    """Raised when emergency stop is active or has been triggered."""


class ComputerDriverError(ComputerError):
    """Raised when underlying OS computer driver fails or lacks system accessibility permissions."""


class LocalProviderError(ProviderError):
    """Base exception for local model provider and runtime failures."""


class LocalRuntimeUnavailableError(LocalProviderError):
    """Raised when local model runtime (e.g. Ollama daemon) is not running or unreachable."""


class LocalModelNotFoundError(LocalProviderError):
    """Raised when requested local model is not installed or found on the local runtime."""


class OfflineModeError(LYRAError):
    """Raised when an external network operation is attempted while offline mode is active."""


class LearningError(LYRAError):
    """Base exception class for learning subsystem operations."""


class LearningStorageError(LearningError):
    """Raised when learning repository or database operations fail."""
