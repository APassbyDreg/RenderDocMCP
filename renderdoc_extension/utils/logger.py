"""
Logger utility for RenderDoc MCP Extension.
Writes log output to the LOG_FILE defined in socket_server.py,
implemented with Python's standard `logging` library.
"""

import logging
import os
import tempfile

# ---------------------------------------------------------------------------
# Log file path (mirrors socket_server.py)
# ---------------------------------------------------------------------------
_IPC_DIR = os.path.join(tempfile.gettempdir(), "renderdoc_mcp")
LOG_FILE = os.path.join(_IPC_DIR, "server.log")

# ---------------------------------------------------------------------------
# Re-export standard level constants for convenience
# ---------------------------------------------------------------------------
LEVEL_DEBUG = logging.DEBUG
LEVEL_INFO = logging.INFO
LEVEL_WARNING = logging.WARNING
LEVEL_ERROR = logging.ERROR

# ---------------------------------------------------------------------------
# Internal logger setup
# ---------------------------------------------------------------------------
_LOGGER_NAME = "renderdoc_mcp"
_logger = logging.getLogger(_LOGGER_NAME)
# capture everything; handlers filter per level
_logger.setLevel(logging.DEBUG)
_logger.propagate = False        # don't bubble up to the root logger

_LOG_FORMAT = "[%(asctime)s.%(msecs)03d] [%(levelname)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_PREV_LOG_FILE = os.path.join(_IPC_DIR, "server-prev.log")


def _ensure_log_dir():
    """Create the IPC directory if it does not exist yet."""
    if not os.path.exists(_IPC_DIR):
        try:
            os.makedirs(_IPC_DIR)
        except OSError:
            pass


def _rotate_log():
    """If server.log already exists, rename it to server-prev.log before opening a new one."""
    if os.path.exists(LOG_FILE):
        try:
            if os.path.exists(_PREV_LOG_FILE):
                os.remove(_PREV_LOG_FILE)
            os.rename(LOG_FILE, _PREV_LOG_FILE)
        except OSError as e:
            import sys
            sys.stderr.write("[Logger] Cannot rotate log file: %s\n" % e)


def _setup_handlers():
    """Attach a FileHandler and a StreamHandler to the logger (once)."""
    if _logger.handlers:
        return  # already initialised

    _ensure_log_dir()
    _rotate_log()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # File handler – write fresh file each run
    try:
        fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        _logger.addHandler(fh)
    except OSError as e:
        import sys
        sys.stderr.write(
            "[Logger] Cannot open log file %s: %s\n" % (LOG_FILE, e))

    # Stream handler – mirrors output to stdout
    sh = logging.StreamHandler()
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(formatter)
    _logger.addHandler(sh)


# Initialise on import
_setup_handlers()


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def set_level(level):
    """Set the minimum log level for all handlers.

    Args:
        level: One of LEVEL_DEBUG, LEVEL_INFO, LEVEL_WARNING, LEVEL_ERROR
               (or any standard ``logging`` integer level).
    """
    _logger.setLevel(level)
    for handler in _logger.handlers:
        handler.setLevel(level)


def set_echo_stdout(enabled):
    """Enable or disable the StreamHandler (stdout mirror).

    Args:
        enabled (bool): Pass ``False`` to suppress stdout output.
    """
    for handler in _logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(
                logging.DEBUG if enabled else logging.CRITICAL + 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_debug(message, *args, **kwargs):
    """Log a DEBUG-level message.

    Args:
        message (str): Message text (supports % formatting via ``args``).
        exc_info (bool): If ``True``, attach the current exception traceback.
    """
    _logger.debug(message, *args, **kwargs)


def log(message, *args, **kwargs):
    """Log an INFO-level message.

    Args:
        message (str): Message text (supports % formatting via ``args``).
        exc_info (bool): If ``True``, attach the current exception traceback.
    """
    _logger.info(message, *args, **kwargs)


def log_warning(message, *args, **kwargs):
    """Log a WARNING-level message.

    Args:
        message (str): Message text (supports % formatting via ``args``).
        exc_info (bool): If ``True``, attach the current exception traceback.
    """
    _logger.warning(message, *args, **kwargs)


def log_error(message, *args, **kwargs):
    """Log an ERROR-level message.

    Args:
        message (str): Message text (supports % formatting via ``args``).
        exc_info (bool): If ``True``, attach the current exception traceback.
    """
    _logger.error(message, *args, **kwargs)


# Aliases
debug = log_debug
info = log
warning = log_warning
error = log_error
