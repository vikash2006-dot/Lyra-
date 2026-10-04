"""Security policy and containment rules for browser automation."""

from dataclasses import dataclass, field
import ipaddress
import os
from pathlib import Path
import re
from urllib.parse import urlparse

from lyra.browser.models import BrowserAction, BrowserActionType, SENSITIVE_FIELD_PATTERN
from lyra.core.exceptions import (
    BrowserConfirmationRequiredError,
    BrowserDownloadLimitError,
    BrowserPolicyViolationError,
)

# Schemes permitted for navigation
ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Blocked schemes that pose code execution or injection risks
BLOCKED_SCHEMES: frozenset[str] = frozenset({"javascript", "data", "vbscript", "about", "chrome"})

# Keywords indicating sensitive or destructive actions requiring user confirmation
DESTRUCTIVE_KEYWORDS: tuple[str, ...] = (
    "delete",
    "remove",
    "destroy",
    "pay",
    "purchase",
    "buy",
    "order",
    "checkout",
    "subscribe",
    "unsubscribe",
    "send",
    "transfer",
    "publish",
    "post",
    "submit",
    "password",
    "reset",
    "change password",
    "update account",
    "deactivate",
    "cancel subscription",
    "upload",
)

# Private / Link-Local IP networks to prevent SSRF
PRIVATE_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / Cloud metadata (169.254.169.254)
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


@dataclass(frozen=True)
class BrowserPolicy:
    """Security policy rules for browser operations."""

    allowed_domains: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ("169.254.169.254", "metadata.google.internal")
    allow_downloads: bool = True
    max_download_size_bytes: int = 10_485_760  # 10 MB
    download_dir: Path = field(default_factory=lambda: Path("downloads"))
    allow_local_network: bool = False  # If True, permits localhost/127.0.0.1 for local test fixtures
    allow_file_scheme: bool = False  # If True, permits file:/// for local HTML fixtures
    require_confirmation_for_destructive: bool = True
    require_confirmation_for_downloads: bool = True
    require_confirmation_for_forms: bool = True

    def verify_url(self, url: str) -> None:
        """Validate target URL against allowed schemes, domain rules, and SSRF protections.

        Raises:
            BrowserPolicyViolationError: If URL violates any security constraint.
        """
        if not url or not isinstance(url, str):
            raise BrowserPolicyViolationError("URL cannot be empty or non-string.")

        parsed = urlparse(url.strip())
        scheme = (parsed.scheme or "").lower()

        # 1. Scheme validation
        if self.allow_file_scheme and scheme == "file":
            return

        if scheme in BLOCKED_SCHEMES:
            raise BrowserPolicyViolationError(
                f"URL scheme '{scheme}:' is blocked for security reasons."
            )

        if scheme not in ALLOWED_SCHEMES:
            raise BrowserPolicyViolationError(
                f"URL scheme '{scheme}:' is not supported. Allowed schemes: {', '.join(sorted(ALLOWED_SCHEMES))}."
            )

        hostname = (parsed.hostname or "").lower().strip()
        if not hostname:
            raise BrowserPolicyViolationError("URL has no valid hostname.")

        # 2. SSRF IP & Link-Local check
        if not self.allow_local_network:
            if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
                raise BrowserPolicyViolationError(
                    f"Navigation to local address '{hostname}' is blocked."
                )

            try:
                ip_obj = ipaddress.ip_address(hostname)
                for net in PRIVATE_NETWORKS:
                    if ip_obj in net:
                        raise BrowserPolicyViolationError(
                            f"Access to private/internal IP '{hostname}' ({net}) is blocked."
                        )
            except ValueError:
                # Not a literal IP address; hostname string
                pass

        # 3. Blocked domains check
        for blocked in self.blocked_domains:
            blocked_clean = blocked.lower().strip()
            if hostname == blocked_clean or hostname.endswith(f".{blocked_clean}"):
                raise BrowserPolicyViolationError(
                    f"Domain '{hostname}' is in the blocked domains list."
                )

        # 4. Allowed domains check (whitelist mode if specified)
        if self.allowed_domains:
            matched = False
            for allowed in self.allowed_domains:
                allowed_clean = allowed.lower().strip()
                if hostname == allowed_clean or hostname.endswith(f".{allowed_clean}"):
                    matched = True
                    break
            if not matched:
                raise BrowserPolicyViolationError(
                    f"Domain '{hostname}' is not in the allowed domains list: {self.allowed_domains}."
                )

    def check_action(self, action: BrowserAction) -> tuple[bool, str | None]:
        """Evaluate if an action requires explicit user confirmation.

        Returns:
            tuple[bool, str | None]: (requires_confirmation, reason)
        """
        # Download actions
        if action.action_type == BrowserActionType.DOWNLOAD:
            if not self.allow_downloads:
                raise BrowserPolicyViolationError("File downloads are disabled by policy.")
            if self.require_confirmation_for_downloads and not action.confirmed:
                return True, f"Downloading file from '{action.target}' requires user confirmation."

        # Check for destructive/sensitive keywords in target or value
        target_lower = action.target.lower()
        value_lower = (action.value or "").lower()

        if self.require_confirmation_for_destructive and not action.confirmed:
            for kw in DESTRUCTIVE_KEYWORDS:
                if kw in target_lower or kw in value_lower:
                    return (
                        True,
                        f"Action '{action.action_type.value}' targets sensitive keyword '{kw}' and requires user confirmation.",
                    )

        # Sensitive form input fill (e.g. password, credit card, auth token)
        if action.action_type == BrowserActionType.FILL and not action.confirmed:
            if action.is_sensitive or SENSITIVE_FIELD_PATTERN.search(target_lower):
                return True, f"Filling sensitive credential/payment field '{action.target}' requires user confirmation."

        # Clicking form submit buttons or submit actions
        if action.action_type == BrowserActionType.CLICK and not action.confirmed:
            if self.require_confirmation_for_forms:
                if any(sub in target_lower for sub in ("submit", "type=submit", "form")):
                    return True, f"Submitting form via '{action.target}' requires user confirmation."

        return False, None

    def enforce_confirmation(self, action: BrowserAction) -> None:
        """Enforce confirmation check or raise BrowserConfirmationRequiredError."""
        requires_conf, reason = self.check_action(action)
        if requires_conf and not action.confirmed:
            raise BrowserConfirmationRequiredError(reason or "Action requires user confirmation.")

    def sanitize_download_filename(self, filename: str) -> str:
        """Sanitize download filename to prevent directory traversal and null byte attacks."""
        if not filename or not isinstance(filename, str):
            return "downloaded_file.bin"

        # Strip null bytes and non-printable characters
        clean = re.sub(r"[\x00-\x1f\x7f]", "", filename)
        # Normalize backslashes to forward slashes to protect against cross-platform traversal
        clean = clean.replace("\\", "/")
        # Take basename only to prevent directory traversal (e.g. ../../etc/passwd)
        base = os.path.basename(clean).strip()
        # Remove any leading dots
        base = base.lstrip(".")
        if not base:
            return "downloaded_file.bin"
        return base

    def verify_download_size(self, size_bytes: int) -> None:
        """Verify downloaded file size does not exceed policy maximum."""
        if size_bytes > self.max_download_size_bytes:
            raise BrowserDownloadLimitError(
                f"Download size {size_bytes} bytes exceeds maximum permitted limit of "
                f"{self.max_download_size_bytes} bytes."
            )
