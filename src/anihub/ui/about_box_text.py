"""Text shared by the About box and the versions dialog."""
from __future__ import annotations

from anihub.core.i18n import tr
from anihub.services.updater import RateLimited


def update_error_text(exc: Exception) -> str:
    """A rate-limited GitHub is explained, not dumped as JSON."""
    return tr("update.rate_limited") if isinstance(exc, RateLimited) else tr("status.error", msg=str(exc))
