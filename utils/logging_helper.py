"""Einheitliches Log-Format für den ganzen Bot."""

import logging
from typing import Any, Optional

LOGGER_NAME = "ZicklaaBotRewrite"


def log_event(
    logger: logging.Logger,
    level: int,
    cog: str,
    action: str,
    /,
    user: Optional[Any] = None,
    user_id: Optional[Any] = None,
    exc_info: bool | BaseException = False,
    **details: Any,
) -> None:
    """Loggt ein Ereignis als ``Cog=… | Action=… | User=… | key=value``.

    Args:
        logger: Der zu verwendende Logger.
        level: Das Logging-Level (z.B. ``logging.INFO``).
        cog: Name des Cogs bzw. Moduls.
        action: Beschreibung der Aktion.
        user: Optionaler Benutzername oder Objekt.
        user_id: Optionale Benutzer-ID.
        exc_info: ``True`` (aktuelle Exception) oder eine Exception für den Traceback.
        **details: Weitere Schlüssel-Wert-Details.
    """
    parts = [f"Cog={cog}", f"Action={action}"]
    if user is not None or user_id is not None:
        parts.append(f"User={user} (ID:{user_id})")
    parts.extend(f"{k}={v}" for k, v in details.items())
    logger.log(level, " | ".join(parts), exc_info=exc_info)
