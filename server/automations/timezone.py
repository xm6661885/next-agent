"""Helpers for interpreting timestamps in the host system timezone.

Timestamps in the database are Unix seconds and therefore timezone-neutral.
Cron expressions, on the other hand, describe wall-clock time and must be
evaluated with the timezone used by the host running AutoTask.
"""

import datetime as _datetime
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_ZONEINFO_ROOT = "/usr/share/zoneinfo"


def _zone_from_key(key):
    if not key:
        return None
    key = key[1:] if key.startswith(":") else key
    # POSIX TZ may point at a zoneinfo file (for example :/etc/localtime).
    if key.startswith("/"):
        path = os.path.realpath(key)
        if path.startswith(_ZONEINFO_ROOT + os.sep):
            key = path[len(_ZONEINFO_ROOT) + 1:]
        else:
            return None
    try:
        return ZoneInfo(key)
    except ZoneInfoNotFoundError:
        return None


def system_timezone():
    """Return the current process/host timezone, including DST rules."""
    # Respect an explicit process timezone just as time.localtime() does.
    tz = _zone_from_key(os.environ.get("TZ"))
    if tz is not None:
        return tz

    try:
        localtime = os.path.realpath("/etc/localtime")
        if localtime.startswith(_ZONEINFO_ROOT + os.sep):
            tz = _zone_from_key(localtime[len(_ZONEINFO_ROOT) + 1:])
            if tz is not None:
                return tz
    except OSError:
        pass

    # This fallback still follows the process timezone, though it may not
    # retain future DST transitions on platforms without a named zone.
    return _datetime.datetime.now().astimezone().tzinfo or _datetime.timezone.utc


def system_timezone_name():
    tz = system_timezone()
    if isinstance(tz, ZoneInfo):
        return tz.key
    return tz.tzname(None) or "UTC"


def local_datetime(timestamp=None):
    """Convert Unix seconds (or use the current instant) to local datetime."""
    tz = system_timezone()
    if timestamp is None:
        return _datetime.datetime.now(tz)
    if isinstance(timestamp, _datetime.datetime):
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=tz)
        return timestamp.astimezone(tz)
    return _datetime.datetime.fromtimestamp(float(timestamp), tz=tz)
