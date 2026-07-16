import numpy as np

def apply_threshold(x, threshold):
    return (x >= threshold).astype(bool)
