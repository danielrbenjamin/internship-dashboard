from urllib.parse import urlsplit

PAGE_PATHS = (
    "/", "/demo", "/jobs", "/where-to-apply", "/saved", "/applied", "/materials",
    "/needs-you", "/background", "/email", "/referrals", "/alerts", "/sources", "/settings", "/analytics", "/interviews",
)


def safe_page(value):
    if not value or len(value) > 1024 or any(ord(character) < 32 for character in value):
        return "/"
    try:
        target = urlsplit(value)
    except ValueError:
        return "/"
    if target.scheme or target.netloc or target.path not in PAGE_PATHS or value.startswith("//"):
        return "/"
    return target.path + (f"?{target.query}" if target.query else "")
