import logging
import logging.handlers
import sys

def get_logger():
    # setup logging
    logger = logging.getLogger()
    logger.handlers = []
    logger.setLevel(logging.INFO)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_fmt = logging.Formatter(fmt='%(asctime)s - %(levelname)s: %(message)s')
    stdout_handler.setFormatter(stdout_fmt)
    logger.addHandler(stdout_handler)
    return logger

