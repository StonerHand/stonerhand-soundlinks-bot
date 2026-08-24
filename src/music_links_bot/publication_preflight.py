from __future__ import annotations

from dataclasses import dataclass

from music_links_bot.models import TrackMatch
from music_links_bot.publication_view import draft_platform_selection


@dataclass(frozen=True, slots=True)
class PreflightIssue:
    code: str
    blocking: bool = False


@dataclass(frozen=True, slots=True)
class PreflightResult:
    issues: tuple[PreflightIssue, ...]

    @property
    def ready(self) -> bool:
        return not any(issue.blocking for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(not issue.blocking for issue in self.issues)

    @property
    def blocking_code(self) -> str | None:
        return next(
            (issue.code for issue in self.issues if issue.blocking),
            None,
        )


def validate_publication(draft: dict, track: TrackMatch) -> PreflightResult:
    """Run fast local checks before a post reaches Telegram."""
    issues: list[PreflightIssue] = []
    if not track.artist.strip() or not track.title.strip():
        issues.append(PreflightIssue("missing_title", blocking=True))
    if not draft.get("source_audio_file_id") and not any(
        isinstance(url, str) and url for url in track.links.values()
    ):
        issues.append(PreflightIssue("missing_links", blocking=True))
    if draft_platform_selection(draft) == [] and not draft.get("source_audio_file_id"):
        issues.append(PreflightIssue("no_platforms", blocking=True))
    if draft.get("as_photo") and not (
        draft.get("custom_cover_file_id") or track.thumbnail_url
    ):
        issues.append(PreflightIssue("missing_cover"))
    if draft.get("intro_truncated"):
        issues.append(PreflightIssue("intro_trimmed"))
    return PreflightResult(tuple(issues))
