import re


def parse_duration(text):
    """Convert a duration such as "1h30m", "45s" or "1h 5m 10s" to seconds.

    Units h, m, s are case-insensitive, each may appear at most once and only
    in that order; whitespace is allowed around the parts. Anything else
    (including an empty string) raises ValueError."""
    match = re.fullmatch(r"\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?\s*", text, re.IGNORECASE)
    if not match or not any(match.groups()):
        raise ValueError(f"invalid duration: {text!r}")
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds
