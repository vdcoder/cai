import re


def parse_duration(text):
    """Convert a duration such as "1h30m", "45s" or "1h 5m 10s" to seconds.

    Units h, m, s are case-insensitive, each may appear at most once and only
    in that order; whitespace is allowed around the parts. Anything else
    (including an empty string) raises ValueError."""
    total = 0
    for number, unit in re.findall(r"(\d+)([hms])", text):
        total += int(number) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total
