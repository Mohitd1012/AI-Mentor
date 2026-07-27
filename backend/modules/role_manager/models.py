"""
Role model — defines an AI persona with personality, expertise, and behavior.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field


class Role(BaseModel):
    """A complete AI persona configuration."""

    id: str = Field(..., description="URL-safe unique id, e.g. 'senior-architect'")
    name: str = Field(..., description="Display name, e.g. 'Senior Software Architect'")
    emoji: str = Field(default="💬", description="Single emoji for the UI badge")

    description: str = Field(
        default="",
        description="Short tagline shown in the role picker",
    )

    # ── Persona ───────────────────────────────────────────────────────────────
    personality: str = Field(
        default="warm, direct, curious",
        description="Personality adjectives blended into the system prompt",
    )
    expertise: list[str] = Field(
        default_factory=list,
        description="Domains the role specializes in",
    )
    teaching_style: Literal["socratic", "direct", "story-driven", "code-first", "metaphor"] = Field(
        default="direct",
        description="How this role explains things",
    )
    humor_level: int = Field(default=2, ge=0, le=5, description="0=serious, 5=very playful")
    response_depth: Literal["brief", "moderate", "thorough"] = Field(default="moderate")

    # ── Behavior ──────────────────────────────────────────────────────────────
    proactivity: int = Field(default=2, ge=0, le=4)
    conversation_mode: Literal["direct", "socratic", "think_aloud"] = Field(default="direct")

    # ── Voice ─────────────────────────────────────────────────────────────────
    voice: str = Field(
        default="af_heart",
        description="Kokoro voice ID (or macOS say voice name)",
    )
    speaking_rate: float = Field(default=1.0, gt=0.3, le=2.0)

    # ── Model preference ──────────────────────────────────────────────────────
    preferred_provider: Optional[str] = Field(default=None,
                                              description="ollama|openai|anthropic|None=auto")
    preferred_model: Optional[str] = Field(default=None)

    # ── System prompt ─────────────────────────────────────────────────────────
    system_prompt: str = Field(
        default="",
        description="Full custom system prompt. Overrides the auto-generated one if non-empty.",
    )

    # ── Metadata ──────────────────────────────────────────────────────────────
    is_builtin: bool = Field(default=False)
    tags: list[str] = Field(default_factory=list)

    def build_system_prompt(self) -> str:
        """
        Returns the system prompt for this role. Uses `system_prompt` field if
        the user provided one, otherwise auto-generates from persona fields.
        """
        if self.system_prompt.strip():
            return self.system_prompt.strip()

        depth_hint = {
            "brief":    "Keep responses very short — 1–2 sentences.",
            "moderate": "Be concise. Lead with the key insight.",
            "thorough": "Provide complete, detailed explanations.",
        }[self.response_depth]

        humor_hint = (
            "Stay strictly professional — no jokes or wordplay."  if self.humor_level <= 1 else
            "Occasional dry humor is welcome."                    if self.humor_level <= 3 else
            "Be playful and witty — humor is part of your charm."
        )

        teaching_hint = {
            "socratic":     "Lead with questions; let the user discover the answer.",
            "direct":       "Give clear answers, then justify briefly.",
            "story-driven": "Use real-world stories and analogies to illustrate concepts.",
            "code-first":   "Show working code first; explain in comments.",
            "metaphor":     "Use vivid metaphors and analogies.",
        }[self.teaching_style]

        expertise_line = (
            f"Your expertise: {', '.join(self.expertise)}." if self.expertise else ""
        )

        return (
            f"You are {self.name}. {self.description}\n\n"
            f"Personality: {self.personality}.\n"
            f"{expertise_line}\n"
            f"Style: {teaching_hint}\n"
            f"{depth_hint} {humor_hint}\n"
            "You observe the user's screen and assist them in real time."
        ).strip()
