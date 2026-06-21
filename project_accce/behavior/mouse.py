import random
import time
from typing import List, Tuple
from playwright.sync_api import Page

# Global tracker for last known mouse position to maintain continuity
_last_mouse_pos: Tuple[float, float] = (100.0, 100.0)

def generate_bezier_points(
    start: Tuple[float, float],
    end: Tuple[float, float],
    steps: int
) -> List[Tuple[float, float]]:
    """
    Generates a list of coordinates interpolating from start to end along a cubic Bézier curve.
    
    B(t) = (1-t)^3 * P0 + 3*(1-t)^2 * t * P1 + 3*(1-t) * t^2 * P2 + t^3 * P3
    """
    p0 = start
    p3 = end
    
    # Generate control points P1 and P2 with random offsets to create natural curvature
    x_diff = p3[0] - p0[0]
    y_diff = p3[1] - p0[1]
    
    p1 = (
        p0[0] + x_diff * random.uniform(0.1, 0.4) + random.uniform(-50, 50),
        p0[1] + y_diff * random.uniform(0.1, 0.4) + random.uniform(-50, 50)
    )
    p2 = (
        p0[0] + x_diff * random.uniform(0.6, 0.9) + random.uniform(-50, 50),
        p0[1] + y_diff * random.uniform(0.6, 0.9) + random.uniform(-50, 50)
    )
    
    points = []
    for i in range(steps + 1):
        t = i / steps
        # Deceleration curve (ease-out-quad equivalent for human deceleration at target)
        t_eased = 1.0 - (1.0 - t) * (1.0 - t)
        
        x = (1 - t_eased)**3 * p0[0] + 3 * (1 - t_eased)**2 * t_eased * p1[0] + 3 * (1 - t_eased) * t_eased**2 * p2[0] + t_eased**3 * p3[0]
        y = (1 - t_eased)**3 * p0[1] + 3 * (1 - t_eased)**2 * t_eased * p1[1] + 3 * (1 - t_eased) * t_eased**2 * p2[1] + t_eased**3 * p3[1]
        
        # Add slight micro-jitter (physical noise) to all points except start/end
        if i > 0 and i < steps:
            x += random.uniform(-1.5, 1.5)
            y += random.uniform(-1.5, 1.5)
            
        points.append((x, y))
        
    return points

def move_mouse_humanized(page: Page, target_x: float, target_y: float):
    """
    Moves the mouse cursor to the target coordinates along a human-like Bézier curve.
    """
    global _last_mouse_pos
    
    start_pos = _last_mouse_pos
    end_pos = (target_x, target_y)
    
    # Calculate step count based on distance to move
    distance = ((end_pos[0] - start_pos[0])**2 + (end_pos[1] - start_pos[1])**2)**0.5
    if distance < 10:
        # Jump directly for tiny adjustments
        page.mouse.move(target_x, target_y)
        _last_mouse_pos = end_pos
        return
        
    steps = int(max(10, min(distance / 20, 35)))
    points = generate_bezier_points(start_pos, end_pos, steps)
    
    for x, y in points:
        page.mouse.move(x, y)
        # Random timing between movements (2-5ms) to simulate physical inertia
        time.sleep(random.uniform(0.002, 0.006))
        
    # Update tracker
    _last_mouse_pos = end_pos
