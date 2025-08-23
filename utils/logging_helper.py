import logging
from typing import Any, Optional


def log_event(
    logger: logging.Logger,
    level: int,
    cog: str,
    action: str,
    user: Optional[Any] = None,
    user_id: Optional[Any] = None,
    exc_info: bool = False,
    **details: Any,
) -> None:
    """Loggt Ereignisse in ein einheitliches Format.

    Args:
        logger: Der zu verwendende Logger.
        level: Das Logging-Level (z.B. ``logging.INFO``).
        cog: Name des Cogs bzw. Moduls.
        action: Beschreibung der Aktion.
        user: Optionaler Benutzername oder Objekt.
        user_id: Optionaler Benutzer- oder Objekt-ID.
        exc_info: Ob Exception-Informationen angehängt werden sollen.
        **details: Weitere Schlüssel-Wert-Details für das Logging.
    """
    parts = [f"Cog={cog}", f"Action={action}"]
    if user is not None or user_id is not None:
        parts.append(f"User={user} (ID:{user_id})")
    if details:
        extra = " | ".join(f"{k}={v}" for k, v in details.items())
        parts.append(extra)
    message = " | ".join(parts)
    logger.log(level, message, exc_info=exc_info)
