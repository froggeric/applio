import os
import sys
import threading
import time
import logging

# 0. Architectural Optimizations (Subagent Nova)
# Enable MPS fallback to prevent crashes on unsupported Metal operators
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
# Ensure torch doesn't try to use CUDA on macOS
os.environ["PYTORCH_ENABLE_METAL_ACCELERATOR"] = "1"

# 1. Path Hygiene (Critical for PyInstaller frozen apps)
if getattr(sys, "frozen", False):
    # If running as a frozen bundle, change the current working directory 
    # to the temporary folder where the app has been extracted.
    # This ensures that relative path imports in app.py work correctly.
    os.chdir(sys._MEIPASS)

# 2. Logging Setup
def setup_logging():
    """
    Sets up logging to a file in the user's Library/Logs directory.
    This is essential for debugging when the console is hidden.
    """
    app_name = "Applio"
    log_dir = os.path.expanduser(f"~/Library/Logs/{app_name}")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "applio_wrapper.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout) # Keep stdout for dev
        ]
    )
    # Redirect stdout/stderr to the log file to capture crashes
    sys.stdout = open(log_file, 'a')
    sys.stderr = open(log_file, 'a')
    
    logging.info("Starting Applio macOS Wrapper...")
    logging.info(f"CWD: {os.getcwd()}")
    logging.info(f"Frozen: {getattr(sys, 'frozen', False)}")

setup_logging()

# 3. Native macOS UI Optimizations (Subagent Orion)
def get_native_menu():
    """
    Creates a standard macOS menu bar. 
    Without an 'Edit' menu, shortcuts like Cmd+C/Cmd+V will not work in the webview.
    """
    from webview.menu import Menu, MenuAction, MenuSeparator
    
    return [
        Menu(
            "Applio",
            [
                MenuAction("About Applio", lambda: None),
                MenuSeparator(),
                MenuAction("Quit", lambda: os._exit(0)),
            ],
        ),
        Menu(
            "Edit",
            [
                MenuAction("Undo", lambda: None),
                MenuAction("Redo", lambda: None),
                MenuSeparator(),
                MenuAction("Cut", lambda: None),
                MenuAction("Copy", lambda: None),
                MenuAction("Paste", lambda: None),
                MenuSeparator(),
                MenuAction("Select All", lambda: None),
            ],
        ),
    ]

# Import pywebview after logging setup
import webview

# Import Applio's launch function
# NOTE: app.py has top-level code that runs on import. 
# We rely on os.chdir happening BEFORE this import.
try:
    from app import launch_gradio
except ImportError as e:
    logging.error(f"Failed to import app.py: {e}")
    sys.exit(1)
except Exception as e:
    logging.error(f"Unexpected error during import: {e}")
    sys.exit(1)

# Global flag to control the server loop
SERVER_PORT = 6969
SERVER_HOST = "127.0.0.1"

def start_server():
    """Starts the Applio Gradio server in a daemon thread."""
    try:
        logging.info(f"Launching Gradio Server on {SERVER_HOST}:{SERVER_PORT}")
        # preventing thread lock is handled by app.py logic usually, 
        # but here we run it in a thread so the UI can proceed.
        launch_gradio(SERVER_HOST, SERVER_PORT)
    except Exception as e:
        logging.error(f"Server crashed: {e}")

def on_closed():
    """Callback when the window is closed."""
    logging.info("Window closed. Exiting...")
    # Force kill the process as Gradio threads can be sticky
    os._exit(0)

if __name__ == "__main__":
    # Start the server in a separate thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait a moment for the server to likely start up (optimistic)
    # A robust check would invoke a request loop, but for now we sleep briefly.
    time.sleep(2)

    # Create the native window
    window_title = "Applio"
    url = f"http://{SERVER_HOST}:{SERVER_PORT}"
    
    logging.info(f"Opening webview window at {url}")
    
    window = webview.create_window(
        window_title, 
        url,
        width=1280,
        height=720,
        resizable=True,
        text_select=True,
        min_size=(800, 600),
        vibrancy=True # Subagent Orion's UX recommendation
    )
    
    webview.start(func=on_closed, menu=get_native_menu())
