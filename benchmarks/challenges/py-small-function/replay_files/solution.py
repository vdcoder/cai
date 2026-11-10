import re


def slugify(text):
    """Lowercase ``text``; every run of characters other than a-z and 0-9
    becomes a single "-"; no leading or trailing "-"."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
