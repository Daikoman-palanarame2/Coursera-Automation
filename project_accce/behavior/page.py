import random
import time
from playwright.sync_api import Page, ElementHandle
from project_accce.behavior.mouse import move_mouse_humanized
from project_accce.behavior.math_utils import poisson_sleep, get_poisson_delay

# Typo neighbor mapping for realistic typing simulation
_NEIGHBOR_KEYS = {
    'a': 's', 'b': 'v', 'c': 'x', 'd': 's', 'e': 'r', 'f': 'g', 'g': 'f',
    'h': 'j', 'i': 'o', 'j': 'h', 'k': 'l', 'l': 'k', 'm': 'n', 'n': 'b',
    'o': 'p', 'p': 'o', 'q': 'w', 'r': 'e', 's': 'a', 't': 'y', 'u': 'i',
    'v': 'c', 'w': 'q', 'x': 'z', 'z': 'x'
}

class HumanizedPage:
    def __init__(self, page: Page):
        self.page = page

    def _get_element_center(self, selector: str) -> tuple:
        """
        Retrieves the absolute center coordinates of an element in the viewport.
        """
        # Resolve locator and wait for visibility
        loc = self.page.locator(selector).first
        loc.wait_for(state="visible")
        loc.scroll_into_view_if_needed()
        
        # Evaluate bounding rect relative to the viewport directly on the element
        box = loc.evaluate('''el => {
            const r = el.getBoundingClientRect();
            return {x: r.left, y: r.top, width: r.width, height: r.height};
        }''')
        
        if not box:
            raise ValueError(f"Element matching selector '{selector}' has no bounding box.")
            
        # Target center with minor random offset to simulate human targeting imprecision
        target_x = box["x"] + box["width"] / 2 + random.uniform(-box["width"]/10, box["width"]/10)
        target_y = box["y"] + box["height"] / 2 + random.uniform(-box["height"]/10, box["height"]/10)
        return target_x, target_y

    def humanized_click(self, selector: str, mean_delay: float = 0.5):
        """
        Moves the mouse to the element center via Bézier curves and clicks it with Poisson delay.
        """
        tx, ty = self._get_element_center(selector)
        
        # Move mouse
        move_mouse_humanized(self.page, tx, ty)
        
        # Short Poisson sleep before click
        poisson_sleep(mean_delay, min_bounds=0.1, max_bounds=1.5)
        
        # Click sequence
        self.page.mouse.down()
        time.sleep(random.uniform(0.05, 0.15))  # Hold button down briefly
        self.page.mouse.up()

    def humanized_type(self, selector: str, text: str, typo_chance: float = 0.05):
        """
        Focuses/clicks the target element and types the text with keystroke timings and typo/backspace corrections.
        """
        self.humanized_click(selector, mean_delay=0.3)
        
        for char in text:
            # Check for typo trigger
            if char.lower() in _NEIGHBOR_KEYS and random.random() < typo_chance:
                typo_char = _NEIGHBOR_KEYS[char.lower()]
                # If original character was uppercase, uppercase the typo
                if char.isupper():
                    typo_char = typo_char.upper()
                
                # Type the incorrect char
                self.page.keyboard.type(typo_char)
                time.sleep(random.uniform(0.08, 0.18))
                
                # Realize the typo: slight pause
                time.sleep(random.uniform(0.15, 0.35))
                
                # Backspace it
                self.page.keyboard.press("Backspace")
                time.sleep(random.uniform(0.05, 0.12))
                
            # Type the correct char
            self.page.keyboard.type(char)
            # Delay between keystrokes modeled on human typing velocity
            time.sleep(random.uniform(0.05, 0.25))

    def humanized_scroll(self, distance: int = None, steps: int = 10):
        """
        Simulates natural scrolling down the page. If distance is None, scrolls all the way to the bottom dynamically.
        """
        if distance is None:
            reached_bottom = False
            for _ in range(60):  # Safety limit of 60 scroll steps
                scroll_info = self.page.evaluate('''() => {
                    return {
                        scrollY: window.scrollY,
                        innerHeight: window.innerHeight,
                        scrollHeight: document.documentElement.scrollHeight
                    };
                }''')
                
                curr_y = scroll_info["scrollY"]
                win_h = scroll_info["innerHeight"]
                doc_h = scroll_info["scrollHeight"]
                
                if curr_y + win_h >= doc_h - 40:
                    reached_bottom = True
                    break
                    
                # Scroll a natural, variable distance (250-450 pixels)
                scroll_dist = random.uniform(250, 450)
                self.page.evaluate(f"window.scrollBy(0, {scroll_dist})")
                
                # Sleep briefly between scrolls
                poisson_sleep(0.3, min_bounds=0.05, max_bounds=0.8)
        else:
            step_distance = distance / steps
            for i in range(steps):
                jitter = random.uniform(-10, 10)
                actual_scroll = step_distance + jitter
                self.page.evaluate(f"window.scrollBy(0, {actual_scroll})")
                poisson_sleep(0.15, min_bounds=0.03, max_bounds=0.5)

    def humanized_goto(self, url: str):
        """
        Navigates to URL and performs a Poisson delay representation of visual scanning loading times.
        """
        import time
        for attempt in range(4):
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                break
            except Exception as e:
                print(f"[ENGINE] Navigation attempt {attempt+1} failed: {e}")
                if attempt < 3:
                    print("[ENGINE] Retrying in 3s...")
                    time.sleep(3)
                else:
                    print("[ENGINE] Falling back to 'commit' wait strategy (stops waiting after header transfer)...")
                    try:
                        self.page.goto(url, wait_until="commit", timeout=20000)
                    except Exception as e2:
                        print(f"[ENGINE] Fallback navigation also failed: {e2}. Continuing anyway to let elements resolve...")
            
        # Sleep for loading analysis
        poisson_sleep(1.8, min_bounds=0.5, max_bounds=5.0)
