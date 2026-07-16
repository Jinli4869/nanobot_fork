"""GUIClaw skill extraction, retrieval, and execution submodules."""

_DESKTOP_PLATFORMS = frozenset({"linux", "macos", "windows"})


def skills_enabled_for_platform(
    platform: str,
    *,
    enable_desktop_skills: bool = False,
) -> bool:
    """Return whether skill features may run on the active platform."""

    return str(platform).strip().lower() not in _DESKTOP_PLATFORMS or enable_desktop_skills
