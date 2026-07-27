"""
Annotation models — mirror the TypeScript types in `desktop/src/overlay/types.ts`.
"""

from typing import Literal, Optional, Union
from pydantic import BaseModel, Field
import uuid


AnnotationColor = Literal["accent", "success", "warning", "danger", "info"]


class BaseAnnotation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    duration_ms: int = 5000          # 0 = persist until cleared
    color: AnnotationColor = "accent"
    label: Optional[str] = None


class HighlightAnnotation(BaseAnnotation):
    kind: Literal["highlight"] = "highlight"
    x: int; y: int; w: int; h: int


class CircleAnnotation(BaseAnnotation):
    kind: Literal["circle"] = "circle"
    x: int; y: int; r: int


class ArrowAnnotation(BaseAnnotation):
    kind: Literal["arrow"] = "arrow"
    x1: int; y1: int; x2: int; y2: int


class LabelAnnotation(BaseAnnotation):
    kind: Literal["label"] = "label"
    x: int; y: int
    text: str


Annotation = Union[
    HighlightAnnotation,
    CircleAnnotation,
    ArrowAnnotation,
    LabelAnnotation,
]
