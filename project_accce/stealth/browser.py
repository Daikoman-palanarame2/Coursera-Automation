import os
from typing import Optional, Dict, Any
from camoufox.sync_api import Camoufox

def launch_stealth_browser(
    headless: bool = True,
    user_data_dir: Optional[str] = None,
    proxy: Optional[Dict[str, Any]] = None
) -> Camoufox:
    """
    Launches a Camoufox stealth browser instance.
    
    Args:
        headless: Whether to run the browser in headless mode.
        user_data_dir: Directory path for persistent state (cookies, storage).
                       If provided, enables persistent context.
        proxy: Dictionary with proxy details (e.g. {'server': 'http://127.0.0.1:8080', 'username': '...', 'password': '...'}).
        
    Returns:
        A Camoufox context manager instance.
    """
    config: Dict[str, Any] = {
        "headless": headless,
    }
    
    if user_data_dir:
        os.makedirs(user_data_dir, exist_ok=True)
        config["persistent_context"] = True
        config["user_data_dir"] = user_data_dir
        
    if proxy:
        config["proxy"] = proxy
        
    # Camoufox automatically handles JA4, canvas noise, and spoofing configurations.
    # Return the Camoufox object to be used inside a 'with' block
    return Camoufox(**config)
