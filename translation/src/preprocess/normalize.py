import numpy as np

def percentile_normalize(x):
    p5 = np.percentile(x, 5)
    p95 = np.percentile(x, 95)
    x = np.clip(x, p5, p95)
    return (x - p5) / (p95 - p5 + 1e-9)

def log_normalize(x):
    x = np.maximum(x, 1e-6)
    lx = np.log(x)
    return percentile_normalize(lx)
