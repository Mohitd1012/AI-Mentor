"""
OCR engine — Apple Vision framework via pyobjc.

Runs VNRecognizeTextRequest on a PIL Image or numpy array.
All ObjC calls are synchronous; callers must run this in an executor.
"""

import io
import logging
import tempfile
import os
from typing import Optional
import numpy as np
from PIL import Image

from modules.screen_capture.models import TextObservation, BoundingBox

logger = logging.getLogger(__name__)

# Cache imports; Vision init has overhead
_vision_available: Optional[bool] = None


def _ensure_vision() -> bool:
    global _vision_available
    if _vision_available is None:
        try:
            import Vision  # noqa: F401
            from Foundation import NSURL  # noqa: F401
            _vision_available = True
        except ImportError:
            logger.warning("pyobjc-framework-Vision not available — OCR disabled")
            _vision_available = False
    return _vision_available


def ocr_image(image: Image.Image) -> list[TextObservation]:
    """
    Run Apple Vision OCR on a PIL Image.
    Returns list of TextObservation sorted top-to-bottom by y position.

    Raises nothing — returns [] on any failure.
    """
    if not _ensure_vision():
        return []

    import Vision
    from Foundation import NSURL

    # Save to temp PNG — NSURL file path is the most reliable input
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
            image.save(f, format="PNG")

        url = NSURL.fileURLWithPath_(tmp_path)
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, {})

        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)

        success, error = handler.performRequests_error_([request], None)

        if not success:
            logger.warning("Vision OCR failed: %s", error)
            return []

        observations: list[TextObservation] = []
        for obs in request.results() or []:
            candidates = obs.topCandidates_(1)
            if not candidates:
                continue
            candidate = candidates[0]
            bb = obs.boundingBox()
            observations.append(TextObservation(
                text=str(candidate.string()),
                confidence=float(candidate.confidence()),
                bbox=BoundingBox(
                    x=float(bb.origin.x),
                    # Vision uses bottom-left origin; flip to top-left
                    y=1.0 - float(bb.origin.y) - float(bb.size.height),
                    width=float(bb.size.width),
                    height=float(bb.size.height),
                ),
            ))

        # Sort top-to-bottom, then left-to-right
        observations.sort(key=lambda o: (round(o.bbox.y, 2), o.bbox.x))
        return observations

    except Exception as exc:
        logger.warning("OCR error: %s", exc)
        return []
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def observations_to_text(observations: list[TextObservation]) -> str:
    """Joins observations into a readable string preserving rough line structure."""
    if not observations:
        return ""

    # Sort top-to-bottom first, then left-to-right within a line
    sorted_obs = sorted(observations, key=lambda o: (round(o.bbox.y, 2), o.bbox.x))

    lines: list[str] = []
    prev_y: Optional[float] = None
    line_parts: list[str] = []

    for obs in sorted_obs:
        y = round(obs.bbox.y, 2)
        if prev_y is not None and abs(y - prev_y) > 0.02:
            if line_parts:
                lines.append(" ".join(line_parts))
            line_parts = []
        line_parts.append(obs.text)
        prev_y = y

    if line_parts:
        lines.append(" ".join(line_parts))

    return "\n".join(lines)


def is_blank_frame(frame_rgb: np.ndarray, threshold: float = 250.0) -> bool:
    """
    Returns True if the frame is uniformly light (screen recording permission denied,
    or screen is actually blank).
    """
    return float(frame_rgb.mean()) > threshold
