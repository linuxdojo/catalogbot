import logging
import logging.handlers
import sys

def get_logger():
    # setup logging
    logger = logging.getLogger()
    logger.handlers = []
    logger.setLevel(logging.INFO)
    stderr_handler = logging.StreamHandler(sys.stdout)
    stderr_fmt = logging.Formatter(fmt='%(asctime)s - %(levelname)s: %(message)s')
    stderr_handler.setFormatter(stderr_fmt)
    logger.addHandler(stderr_handler)
    return logger

