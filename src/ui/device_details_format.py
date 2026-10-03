"""Small formatting helpers for the device details dialog."""


HEALTH_REFRESH_MS = 5000


def _format_bytes(num_bytes):
    """Render a byte count as a short human-readable size such as '41.2 GB'."""
    size = float(num_bytes or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f"{int(size)} {unit}" if unit == 'B' else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _format_duration(seconds):
    """Render a number of seconds as '4 days, 2 hours, 11 minutes'."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return ''
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days > 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return ', '.join(parts)
