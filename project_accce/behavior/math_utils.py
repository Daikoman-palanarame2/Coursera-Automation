import random
import time

def get_poisson_delay(mean_delay: float, min_bounds: float = 0.1, max_bounds: float = 30.0) -> float:
    """
    Generates a non-linear delay interval based on an exponential distribution 
    (the time between events in a Poisson process).
    
    Args:
        mean_delay: Target average delay in seconds (1/rate).
        min_bounds: Floor boundary to prevent instantaneous double-actions.
        max_bounds: Ceiling boundary to prevent excessive lockouts/freezes.
        
    Returns:
        A randomized sleep duration in seconds.
    """
    if mean_delay <= 0:
        return 0.0
    
    # Python's expovariate takes the rate parameter lambda = 1.0 / mean
    rate = 1.0 / mean_delay
    delay = random.expovariate(rate)
    
    # Enforce realistic bounds
    return max(min_bounds, min(delay, max_bounds))

def poisson_sleep(mean_delay: float, min_bounds: float = 0.1, max_bounds: float = 30.0):
    """
    Blocks execution for a random delay based on a Poisson process interval.
    """
    delay = get_poisson_delay(mean_delay, min_bounds, max_bounds)
    time.sleep(delay)
