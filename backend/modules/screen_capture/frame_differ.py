"""
Frame differ — skip OCR when the screen has not meaningfully changed.

Uses a combination of:
  1. Mean pixel value delta (catches uniform brightness changes quickly)
  2. Perceptual hash Hamming distance (catches content changes)

Two frames are "different" when either signal exceeds its threshold.
"""

import numpy as np
from typing import Optional

HASH_SIZE = 16
DEFAULT_HASH_THRESHOLD = 10    # bits out of 256
DEFAULT_MEAN_THRESHOLD = 5.0   # absolute mean pixel delta (0–255)


def _phash(gray: np.ndarray) -> np.ndarray:
    """
    Average perceptual hash of a grayscale 2-D array already downsampled to
    HASH_SIZE × HASH_SIZE. Returns bool array (True = above row mean).
    Uses per-row means so uniform images still produce a valid hash.
    """
    row_means = gray.mean(axis=1, keepdims=True)  # shape (H, 1)
    return gray > row_means


class FrameDiffer:
    def __init__(
        self,
        threshold: int = DEFAULT_HASH_THRESHOLD,
        mean_threshold: float = DEFAULT_MEAN_THRESHOLD,
    ) -> None:
        self._hash_threshold = threshold
        self._mean_threshold = mean_threshold
        self._last_hash: Optional[np.ndarray] = None
        self._last_mean: Optional[float] = None

    def has_changed(self, frame_rgb: np.ndarray) -> bool:
        """
        Returns True if the frame differs enough from the last seen frame.
        Always returns True on the first call.
        """
        from PIL import Image
        # Downsample once for both signals
        gray_img = Image.fromarray(frame_rgb).convert("L").resize(
            (HASH_SIZE, HASH_SIZE), Image.LANCZOS
        )
        gray = np.array(gray_img, dtype=np.float32)
        current_hash = _phash(gray)
        current_mean = float(gray.mean())

        if self._last_hash is None:
            self._last_hash = current_hash
            self._last_mean = current_mean
            return True

        mean_delta = abs(current_mean - self._last_mean)
        hash_dist = int(np.sum(current_hash != self._last_hash))
        changed = (hash_dist >= self._hash_threshold) or (mean_delta >= self._mean_threshold)

        if changed:
            self._last_hash = current_hash
            self._last_mean = current_mean

        return changed

    def reset(self) -> None:
        self._last_hash = None
        self._last_mean = None
