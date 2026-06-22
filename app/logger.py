import logging
import sys
from .constants import BOT_LOG_FILE, ERRORS_LOG_FILE

def setup_logger(name="QUANTUM BINGX"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
        
        # Console Handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        
        # File Handler (General)
        fh = logging.FileHandler(BOT_LOG_FILE)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        
        # File Handler (Errors)
        eh = logging.FileHandler(ERRORS_LOG_FILE)
        eh.setLevel(logging.ERROR)
        eh.setFormatter(fmt)
        
        logger.addHandler(ch)
        logger.addHandler(fh)
        logger.addHandler(eh)
    return logger

logger = setup_logger()