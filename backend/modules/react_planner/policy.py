"""
Mode policy — deterministic transformation of planner decisions.

The planner suggests an action; the policy can override it based on the
user-selected ConversationMode and proactivity level. Doing this in code
(not prompt) keeps mode behavior predictable across different models.
"""

from modules.react_planner.models import (
    Action, ConversationMode, PlannerDecision,
)


def apply_policy(
    decision: PlannerDecision,
    mode: ConversationMode,
    proactivity: int,
    user_message: str,
) -> PlannerDecision:
    action = decision.action

    # ── Proactivity gate ──────────────────────────────────────────────────────
    # Level 0 → only respond to direct questions
    user_lc = user_message.strip().lower()
    is_direct_question = "?" in user_message or user_lc.startswith(
        ("how", "what", "why", "when", "where", "can ", "could ", "should ", "is ", "are ")
    )

    if proactivity == 0 and not is_direct_question:
        return PlannerDecision(
            action=Action.SILENT,
            reasoning="proactivity=0; user did not ask a direct question",
        )

    # ── Mode transformations ─────────────────────────────────────────────────
    if mode == ConversationMode.SOCRATIC:
        # Socratic never just teaches on the first move
        if action == Action.TEACH:
            return PlannerDecision(
                action=Action.CHALLENGE,
                reasoning=f"socratic mode: TEACH→CHALLENGE ({decision.reasoning})",
            )

    elif mode == ConversationMode.THINK_ALOUD:
        # Think-aloud: bias toward SUMMARIZE so user keeps verbalizing
        if action == Action.TEACH and len(user_message.split()) > 12:
            return PlannerDecision(
                action=Action.SUMMARIZE,
                reasoning=f"think-aloud: TEACH→SUMMARIZE (verbose input)",
            )

    return decision
