import os
import sys
import threading
import webview
import main

# Ensure we're running from the correct directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from gui_backend import ACCCEBackend

# System tray support
try:
    from pystray import Icon, Menu, MenuItem
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False


class ACCCEApp:
    def __init__(self):
        self.backend = ACCCEBackend()
        self.window = None
        self.tray_icon = None
        self._minimized_to_tray = False
    
    def _create_tray_icon_image(self):
        """Generate a simple tray icon programmatically (blue gradient circle with 'A')."""
        size = 64
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Draw a blue circle
        draw.ellipse([4, 4, size-4, size-4], fill=(59, 130, 246, 255))
        # Draw letter 'A' in center
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("arial.ttf", 32)
        except Exception:
            font = ImageFont.load_default()
        draw.text((size//2, size//2), "A", fill=(255, 255, 255, 255), font=font, anchor="mm")
        return img
    
    def _setup_tray(self):
        """Setup system tray icon with menu."""
        if not HAS_TRAY:
            return
        
        icon_image = self._create_tray_icon_image()
        
        menu = Menu(
            MenuItem("Show ACCCE", self._show_from_tray, default=True),
            MenuItem("Quit", self._quit_from_tray)
        )
        
        self.tray_icon = Icon("ACCCE", icon_image, "ACCCE - Coursera Engine", menu)
        tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        tray_thread.start()
    
    def _show_from_tray(self, icon=None, item=None):
        """Restore window from system tray."""
        if self.window:
            self.window.show()
            self.window.restore()
            self._minimized_to_tray = False
    
    def _quit_from_tray(self, icon=None, item=None):
        """Quit the application from the tray."""
        self.backend.cleanup()
        if self.tray_icon:
            self.tray_icon.stop()
        if self.window:
            self.window.destroy()
    
    def _on_closing(self):
        """Called when user clicks the X button. Minimize to tray instead of closing."""
        if HAS_TRAY and self.tray_icon:
            self.window.hide()
            self._minimized_to_tray = True
            return False  # Prevent window destruction
        else:
            self.backend.cleanup()
            return True  # Allow window destruction
    
    def _on_closed(self):
        """Called when window is destroyed."""
        self.backend.cleanup()
        if self.tray_icon:
            self.tray_icon.stop()
    
    def run(self):
        """Launch the ACCCE desktop application."""
        # Determine the HTML file path
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_frontend.html")
        
        if not os.path.exists(html_path):
            print(f"ERROR: Frontend file not found: {html_path}")
            sys.exit(1)
        
        # Setup system tray
        self._setup_tray()
        
        # Create PyWebView window
        self.window = webview.create_window(
            title="ACCCE — Coursera Automation Engine",
            url=html_path,
            js_api=self.backend,
            width=1100,
            height=750,
            min_size=(900, 600),
            background_color="#0b0f19",
            confirm_close=True,
        )
        
        self.window.events.closing += self._on_closing
        self.window.events.closed += self._on_closed
        
        # Start the webview event loop
        webview.start(debug=False)


if __name__ == "__main__":
    if len(sys.argv) > 1 and "--course-id" in sys.argv:
        if "main.py" in sys.argv:
            sys.argv.remove("main.py")
        import main
        main.main()
    else:
        app = ACCCEApp()
        app.run()
