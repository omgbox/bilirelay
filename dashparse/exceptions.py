class DashParseError(Exception):
    """Base exception for dashparse."""


class MPDValidationError(DashParseError):
    """MPD XML is invalid or missing required attributes."""


class SegmentFetchError(DashParseError):
    """HTTP error while fetching a segment."""


class SIDXParseError(DashParseError):
    """Failed to parse sidx box."""


class TemplateExpansionError(DashParseError):
    """Template variable expansion failed (missing $Number$, etc.)."""


class UnsupportedProfileError(DashParseError):
    """MPD profile is not supported."""
