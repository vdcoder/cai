def parse_duration(text):
    """Convert a duration such as "1h30m", "45s" or "1h 5m 10s" to seconds.

    Units h, m, s are case-insensitive, each may appear at most once and only
    in that order; whitespace is allowed around the parts. Anything else
    (including an empty string) raises ValueError."""
    raise NotImplementedError
