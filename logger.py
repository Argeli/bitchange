import logging

formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

def setup_logger(name, file, level=logging.INFO):
    """Set-up a logger quickly"""
    logger = logging.getLogger(name)
    
    handler = logging.FileHandler(file)        
    handler.setFormatter(formatter)
    
    logger.setLevel(level)
    logger.addHandler(handler)
    
    return logger