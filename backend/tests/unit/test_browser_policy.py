"""Unit tests for BrowserPolicy security rules, domain controls, and confirmation checks."""

from pathlib import Path
import pytest

from lyra.browser.models import BrowserAction, BrowserActionType
from lyra.browser.policy import BrowserPolicy
from lyra.core.exceptions import (
    BrowserConfirmationRequiredError,
    BrowserDownloadLimitError,
    BrowserPolicyViolationError,
)


def test_browser_policy_default_url_validation_success():
    policy = BrowserPolicy()
    # Allowed standard web URLs
    policy.verify_url("https://example.com")
    policy.verify_url("http://subdomain.test.org/path?q=1")


def test_browser_policy_blocked_schemes():
    policy = BrowserPolicy()
    with pytest.raises(BrowserPolicyViolationError, match="blocked for security reasons"):
        policy.verify_url("javascript:alert(1)")

    with pytest.raises(BrowserPolicyViolationError, match="blocked for security reasons"):
        policy.verify_url("data:text/html,<b>pwned</b>")

    with pytest.raises(BrowserPolicyViolationError, match="is not supported"):
        policy.verify_url("ftp://ftp.example.com/file.txt")

    with pytest.raises(BrowserPolicyViolationError, match="is not supported"):
        policy.verify_url("file:///etc/passwd")


def test_browser_policy_file_scheme_override_for_tests():
    policy = BrowserPolicy(allow_file_scheme=True)
    # When enabled for tests, file scheme does not raise
    policy.verify_url("file:///path/to/test.html")


def test_browser_policy_ssrf_and_private_network_blocking():
    policy = BrowserPolicy()

    # Localhost
    with pytest.raises(BrowserPolicyViolationError, match="blocked"):
        policy.verify_url("http://localhost:8080")
    with pytest.raises(BrowserPolicyViolationError, match="blocked"):
        policy.verify_url("http://127.0.0.1:3000")

    # Cloud metadata (169.254.169.254)
    with pytest.raises(BrowserPolicyViolationError, match="blocked"):
        policy.verify_url("http://169.254.169.254/latest/meta-data/")

    # Private subnets
    with pytest.raises(BrowserPolicyViolationError, match="Access to private/internal IP"):
        policy.verify_url("http://10.0.0.1/admin")
    with pytest.raises(BrowserPolicyViolationError, match="Access to private/internal IP"):
        policy.verify_url("http://192.168.1.1/router")
    with pytest.raises(BrowserPolicyViolationError, match="Access to private/internal IP"):
        policy.verify_url("http://172.16.0.5")


def test_browser_policy_local_network_allowed_for_testing():
    policy = BrowserPolicy(allow_local_network=True)
    policy.verify_url("http://127.0.0.1:8000")
    policy.verify_url("http://localhost:3000")


def test_browser_policy_blocked_domains():
    policy = BrowserPolicy(blocked_domains=("evil.com", "malware.net"))
    with pytest.raises(BrowserPolicyViolationError, match="blocked domains list"):
        policy.verify_url("https://evil.com/login")
    with pytest.raises(BrowserPolicyViolationError, match="blocked domains list"):
        policy.verify_url("https://sub.evil.com/page")

    # Unblocked domain succeeds
    policy.verify_url("https://good.com")


def test_browser_policy_allowed_domains_whitelist():
    policy = BrowserPolicy(allowed_domains=("trusted.com", "partner.org"))
    # In whitelist
    policy.verify_url("https://trusted.com/api")
    policy.verify_url("https://sub.trusted.com/doc")

    # Not in whitelist
    with pytest.raises(BrowserPolicyViolationError, match="not in the allowed domains list"):
        policy.verify_url("https://unknown.com")


def test_browser_policy_action_confirmation_detection():
    policy = BrowserPolicy()

    # Safe click
    safe_click = BrowserAction(
        action_type=BrowserActionType.CLICK,
        target="#next-page",
    )
    req, reason = policy.check_action(safe_click)
    assert not req
    assert reason is None

    # Destructive click
    delete_click = BrowserAction(
        action_type=BrowserActionType.CLICK,
        target="button.btn-delete-account",
    )
    req, reason = policy.check_action(delete_click)
    assert req
    assert "delete" in reason.lower()

    # Confirmed destructive click
    confirmed_delete = BrowserAction(
        action_type=BrowserActionType.CLICK,
        target="button.btn-delete-account",
        confirmed=True,
    )
    req, reason = policy.check_action(confirmed_delete)
    assert not req

    # Sensitive form fill (password)
    password_fill = BrowserAction(
        action_type=BrowserActionType.FILL,
        target="input#password",
        value="supersecret123",
    )
    req, reason = policy.check_action(password_fill)
    assert req
    assert "password" in reason.lower()

    # Form submit button click
    submit_click = BrowserAction(
        action_type=BrowserActionType.CLICK,
        target="button[type=submit]",
    )
    req, reason = policy.check_action(submit_click)
    assert req

    # Download action always requires confirmation
    download_action = BrowserAction(
        action_type=BrowserActionType.DOWNLOAD,
        target="https://example.com/report.pdf",
    )
    req, reason = policy.check_action(download_action)
    assert req
    assert "download" in reason.lower()


def test_browser_policy_enforce_confirmation_raises():
    policy = BrowserPolicy()
    unconfirmed = BrowserAction(
        action_type=BrowserActionType.CLICK,
        target="button#purchase-now",
        confirmed=False,
    )
    with pytest.raises(BrowserConfirmationRequiredError, match="requires user confirmation"):
        policy.enforce_confirmation(unconfirmed)


def test_browser_policy_sanitize_download_filename():
    policy = BrowserPolicy()
    assert policy.sanitize_download_filename("report.pdf") == "report.pdf"
    assert policy.sanitize_download_filename("../../etc/passwd") == "passwd"
    assert policy.sanitize_download_filename("..\\windows\\system32\\cmd.exe") == "cmd.exe"
    assert policy.sanitize_download_filename("   .hidden   ") == "hidden"
    assert policy.sanitize_download_filename("") == "downloaded_file.bin"


def test_browser_policy_verify_download_size():
    policy = BrowserPolicy(max_download_size_bytes=1000)
    policy.verify_download_size(500)  # OK
    with pytest.raises(BrowserDownloadLimitError, match="exceeds maximum permitted limit"):
        policy.verify_download_size(1500)
