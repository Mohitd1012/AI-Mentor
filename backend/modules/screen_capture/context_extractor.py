"""
Context extractor — converts raw OCR text + app info into a structured ScreenContext.

Classifies content type, extracts entities (URLs, errors, file paths, code).
"""

import re
import logging
from typing import Optional

from modules.screen_capture.models import (
    ActiveApp, ContentType, ScreenContext, TextObservation,
)
from modules.screen_capture import masker

logger = logging.getLogger(__name__)

# ── Content-type signals ───────────────────────────────────────────────────────

_BROWSER_BUNDLES = {
    "com.apple.Safari", "com.google.Chrome", "org.mozilla.firefox",
    "com.microsoft.edgemac", "com.brave.Browser",
}
_IDE_BUNDLES = {
    "com.microsoft.VSCode", "com.jetbrains.intellij", "com.jetbrains.pycharm",
    "com.jetbrains.goland", "com.jetbrains.webstorm",
    "com.todesktop.230313mzl4w4u92",  # Cursor
}
_TERMINAL_BUNDLES = {
    "com.apple.Terminal", "com.googlecode.iterm2",
    "dev.warp.desktop", "com.github.warp",
}

_URL_RE = re.compile(r'https?://[^\s<>"\']+')
_FILE_PATH_RE = re.compile(r'(?:^|[\s"])(/(?:[\w.\-]+/)*[\w.\-]+\.\w+)')
_ERROR_RE = re.compile(
    r'(?i)(error|exception|traceback|fatal|failed|warning).*',
    re.MULTILINE,
)
_CODE_FENCE_RE = re.compile(r'(?:def |class |import |from |const |let |var |fn |func )')


def _classify_content(app: Optional[ActiveApp], text: str) -> ContentType:
    if app:
        bid = app.bundle_id
        if bid in _BROWSER_BUNDLES:
            return ContentType.BROWSER
        if bid in _IDE_BUNDLES:
            return ContentType.CODE
        if bid in _TERMINAL_BUNDLES:
            return ContentType.TERMINAL
        name = app.name.lower()
        if any(x in name for x in ("code", "cursor", "vim", "emacs", "xcode")):
            return ContentType.CODE
        if any(x in name for x in ("terminal", "iterm", "warp", "shell")):
            return ContentType.TERMINAL
        if any(x in name for x in ("safari", "chrome", "firefox")):
            return ContentType.BROWSER
        if any(x in name for x in ("excel", "numbers", "sheets")):
            return ContentType.SPREADSHEET
        if any(x in name for x in ("word", "pages", "notion", "obsidian")):
            return ContentType.DOCUMENT
        if any(x in name for x in ("slack", "discord", "teams", "telegram")):
            return ContentType.CHAT

    # Text-based heuristics
    if _CODE_FENCE_RE.search(text):
        return ContentType.CODE
    if re.search(r'^\$|^>|^#', text, re.MULTILINE):
        return ContentType.TERMINAL

    return ContentType.UNKNOWN


def extract(
    observations: list[TextObservation],
    raw_text: str,
    active_app: Optional[ActiveApp],
    capture_w: int,
    capture_h: int,
    is_blank: bool,
) -> ScreenContext:

    masked = masker.mask(raw_text)
    urls = _URL_RE.findall(masked)
    errors = [m.group(0)[:200] for m in _ERROR_RE.finditer(masked)]
    file_paths = _FILE_PATH_RE.findall(masked)
    content_type = _classify_content(active_app, masked)

    # Extract short code snippets (lines containing code keywords, max 5)
    code_lines = [
        line.strip() for line in masked.splitlines()
        if _CODE_FENCE_RE.search(line)
    ][:5]

    return ScreenContext(
        active_app=active_app,
        raw_text=raw_text,
        observations=observations,
        content_type=content_type,
        file_path=file_paths[0] if file_paths else None,
        urls=list(dict.fromkeys(urls))[:5],           # deduplicated, max 5
        error_messages=list(dict.fromkeys(errors))[:5],
        code_snippets=code_lines,
        masked_text=masked,
        is_blank=is_blank,
        capture_width=capture_w,
        capture_height=capture_h,
    )
