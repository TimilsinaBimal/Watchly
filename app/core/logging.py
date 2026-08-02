import sys

from loguru import logger

from app.core.config import settings

# loguru's default format minus the markup, so it reads the same piped to a file.
LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"


def configure_logging() -> None:
    """Replace loguru's default handler with a configured one.

    Nothing configured loguru before, so the app ran on its defaults: every debug
    line emitted regardless of environment, and — the reason this matters —
    `diagnose=True`, which annotates tracebacks with the *values* of variables in
    the failing frame.

    That is a credential leak here. `stremio/auth.py` holds a payload containing the
    user's email and password across the call that can raise, and the handler logs
    the traceback; the same is true anywhere decrypted API keys are in scope. Turning
    diagnose off is the whole point of this module.
    """
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format=LOG_FORMAT,
        # Never on: it prints variable values from every frame in the traceback.
        diagnose=False,
        # The frame chain is still useful, and it carries no user data.
        backtrace=True,
        enqueue=False,
    )
