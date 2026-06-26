import logging
import sys

from modules import shared
from reactor_utils import addLoggingLevel


# Create a new logger
logger = logging.getLogger("ReActor")
logger.propagate = False

# Add Custom Level
# logging.addLevelName(logging.INFO, "STATUS")
addLoggingLevel("STATUS", logging.INFO + 5)

# Add handler if we don't have one.
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("[%(name)s] %(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(handler)

# Configure logger
loglevel_string = getattr(shared.cmd_opts, "reactor_loglevel", "INFO")
loglevel = getattr(logging, loglevel_string.upper(), "info")
logger.setLevel(loglevel)
