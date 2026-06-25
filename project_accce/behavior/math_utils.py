import random
import time

# ---------------------------------------------------------------------------
# Global speed multiplier — set once at startup via set_speed_factor().
# 1.0 = full human-like timing (Safe)
# 0.4 = 60% faster (Balanced)
# 0.1 = minimum delays only (Turbo)
# ---------------------------------------------------------------------------
_SPEED_FACTOR: float = 1.0

def set_speed_factor(factor: float) -> None:
    """Set the global speed multiplier (called once from main() at startup)."""
    global _SPEED_FACTOR
    _SPEED_FACTOR = max(0.05, float(factor))  # never go below 5% to avoid crashes

def get_speed_factor() -> float:
    """Return the current speed multiplier."""
    return _SPEED_FACTOR

def get_poisson_delay(mean_delay: float, min_bounds: float = 0.1, max_bounds: float = 30.0) -> float:
    """
    Generates a non-linear delay interval based on an exponential distribution 
    (the time between events in a Poisson process).
    
    Args:
        mean_delay: Target average delay in seconds (1/rate).
        min_bounds: Floor boundary to prevent instantaneous double-actions.
        max_bounds: Ceiling boundary to prevent excessive lockouts/freezes.
        
    Returns:
        A randomized sleep duration in seconds, scaled by the global speed factor.
    """
    if mean_delay <= 0:
        return 0.0
    
    # Scale the mean by the speed factor before computing the Poisson delay
    scaled_mean = mean_delay * _SPEED_FACTOR
    if scaled_mean <= 0:
        return 0.0

    # Python's expovariate takes the rate parameter lambda = 1.0 / mean
    rate = 1.0 / scaled_mean
    delay = random.expovariate(rate)
    
    # Scale bounds too so min/max respect the speed mode
    scaled_min = min_bounds * _SPEED_FACTOR
    scaled_max = max_bounds * _SPEED_FACTOR

    # Enforce realistic bounds
    return max(scaled_min, min(delay, scaled_max))

def poisson_sleep(mean_delay: float, min_bounds: float = 0.1, max_bounds: float = 30.0):
    """
    Blocks execution for a random delay based on a Poisson process interval,
    automatically scaled by the global speed factor.
    """
    delay = get_poisson_delay(mean_delay, min_bounds, max_bounds)
    time.sleep(delay)

