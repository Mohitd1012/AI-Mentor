"""
Active application tracker using macOS NSWorkspace.
"""

import logging
from typing import Optional
from modules.screen_capture.models import ActiveApp

logger = logging.getLogger(__name__)

# Apps that should never be captured (privacy-critical by default)
DEFAULT_EXCLUDED_BUNDLES = {
    "com.apple.keychainaccess",
    "com.apple.systempreferences",
    "com.1password.1password",
    "com.agilebits.onepassword7",
    "com.lastpass.lastpassmacdesktop",
}


def get_active_app() -> Optional[ActiveApp]:
    try:
        from AppKit import NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        app = ws.frontmostApplication()
        if app is None:
            return None
        return ActiveApp(
            name=app.localizedName() or "Unknown",
            bundle_id=app.bundleIdentifier() or "",
            pid=app.processIdentifier(),
        )
    except Exception as exc:
        logger.warning("Could not get active app: %s", exc)
        return None


def is_excluded(app: Optional[ActiveApp], excluded_bundles: set[str]) -> bool:
    if app is None:
        return False
    all_excluded = DEFAULT_EXCLUDED_BUNDLES | excluded_bundles
    return app.bundle_id in all_excluded
