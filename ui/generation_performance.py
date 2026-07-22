from __future__ import annotations


DESKTOP_PREVIEW_INTERVAL_SECONDS = 1.0 / 8.0
MOBILE_PREVIEW_INTERVAL_SECONDS = 1.0


def is_mobile_user_agent(user_agent: str | None) -> bool:
    """Match the mobile browser family used by the frontend layout code."""
    value = str(user_agent or "")
    return "Mobile" in value and "AppleWebKit" in value


def generation_preview_interval(is_mobile: bool) -> float:
    """Return the minimum interval between generation preview renders."""
    return MOBILE_PREVIEW_INTERVAL_SECONDS if is_mobile else DESKTOP_PREVIEW_INTERVAL_SECONDS


def force_generation_preview(is_mobile: bool, *, step_changed: bool, new_step_frame: bool) -> bool:
    """Desktop keeps immediate step updates; mobile waits for its render interval."""
    return (not is_mobile) and (step_changed or new_step_frame)
