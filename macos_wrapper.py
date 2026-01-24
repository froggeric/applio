import os
import sys
import threading
import time
import logging
import socket
import http.server
import socketserver

# 0. Architectural Optimizations (Subagent Nova)
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["PYTORCH_ENABLE_METAL_ACCELERATOR"] = "1"

# 0.1 Redirect Cache Directories
APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/Applio")
os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
os.environ["HF_HOME"] = os.path.join(APP_SUPPORT_DIR, "huggingface")
os.environ["HF_DATASETS_CACHE"] = os.path.join(APP_SUPPORT_DIR, "huggingface", "datasets")
os.environ["TRANSFORMERS_CACHE"] = os.path.join(APP_SUPPORT_DIR, "huggingface", "models")
os.environ["MPLCONFIGDIR"] = os.path.join(APP_SUPPORT_DIR, "matplotlib")
os.environ["TORCH_HOME"] = os.path.join(APP_SUPPORT_DIR, "torch")

# 1. Path Hygiene
if getattr(sys, "frozen", False):
    os.chdir(sys._MEIPASS)

# 2. Logging Setup
def setup_logging():
    app_name = "Applio"
    log_dir = os.path.expanduser(f"~/Library/Logs/{app_name}")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "applio_wrapper.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode='w'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    sys.stdout = open(log_file, 'w')
    sys.stderr = open(log_file, 'w')
    logging.info("Starting Applio macOS Wrapper...")
    logging.info("Wrapper Version: 1.6 (Stub Server Loading Screen)")
    logging.info(f"CWD: {os.getcwd()}")
    logging.info(f"Frozen: {getattr(sys, 'frozen', False)}")

setup_logging()

# 3. Native macOS UI Optimizations
def get_native_menu():
    from webview.menu import Menu, MenuAction, MenuSeparator
    return [
        Menu("Applio", [MenuAction("About Applio", lambda: None), MenuSeparator(), MenuAction("Quit", lambda: os._exit(0))]),
        Menu("Edit", [MenuAction("Undo", lambda: None), MenuAction("Redo", lambda: None), MenuSeparator(), MenuAction("Cut", lambda: None), MenuAction("Copy", lambda: None), MenuAction("Paste", lambda: None), MenuSeparator(), MenuAction("Select All", lambda: None)]),
    ]

import webview

# Global Configuration
SERVER_PORT = 6969
SERVER_HOST = "127.0.0.1"
LOADING_PORT = 5678

# Loading Screen HTML
LOADING_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Applio is Starting</title>
    <style>
        body { background-color: #0f0f0f; color: #ffffff; font-family: -apple-system, sans-serif; display: flex; flex-direction: column; justify_content: center; align-items: center; height: 100vh; margin: 0; user-select: none; }
        .loader { width: 48px; height: 48px; border: 5px solid #333; border-bottom-color: #fff; border-radius: 50%; display: inline-block; box-sizing: border-box; animation: rotation 1s linear infinite; margin-bottom: 20px; }
        @keyframes rotation { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        h1 { font-size: 24px; font-weight: 500; margin-bottom: 10px; }
        p { color: #888; font-size: 14px; }
    </style>
</head>
<body>
    <div class="loader"></div>
    <h1>Starting Applio...</h1>
    <p>Initializing AI models and backend services.</p>
    <p>This may take a few minutes on first run.</p>
</body>
</html>
"""

class LoadingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(LOADING_HTML.encode("utf-8"))
    def log_message(self, format, *args):
        pass # Silence logs

def start_loading_server():
    """Starts a minimal HTTP server to serve the loading screen."""
    try:
        handler = LoadingHandler
        with socketserver.TCPServer(("127.0.0.1", LOADING_PORT), handler) as httpd:
            logging.info(f"Loading Server started on port {LOADING_PORT}")
            httpd.serve_forever() # Daemon thread will kill this on exit
    except Exception as e:
        logging.error(f"Loading Server failed: {e}")

def wait_for_server(host, port, timeout=300):
    import urllib.request
    url = f"http://{host}:{port}"
    start_time = time.time()
    logging.info(f"Waiting for {url} to be responsive...")
    while time.time() - start_time < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    logging.info("Server responded with 200 OK!")
                    return True
        except Exception:
            time.sleep(1)
    return False

def start_server():
    try:
        # Lazy import to prevent infinite loops
        try:
            from app import launch_gradio
        except ImportError as e:
            logging.error(f"Failed to import app.py: {e}")
            return
        logging.info(f"Launching Gradio Server on {SERVER_HOST}:{SERVER_PORT}")
        launch_gradio(SERVER_HOST, SERVER_PORT)
    except Exception as e:
        logging.error(f"Server crashed: {e}")

def on_closed():
    logging.info("Window closed. Exiting...")
    os._exit(0)

if __name__ == "__main__":
    sys.argv = [sys.argv[0]]
    import multiprocessing
    multiprocessing.freeze_support()

    # 1. Start Loading Server
    loading_thread = threading.Thread(target=start_loading_server, daemon=True)
    loading_thread.start()
    
    # 2. Start App Server
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # 3. Create Window pointing to Loading Server
    window = webview.create_window(
        "Applio", 
        url=f"http://127.0.0.1:{LOADING_PORT}",
        width=1280, 
        height=720, 
        resizable=True, 
        text_select=True,
        min_size=(800, 600)
        # vibrancy=True
    )

    # 4. Monitor Thread to switch URL
    def monitor_and_switch():
        if wait_for_server(SERVER_HOST, SERVER_PORT):
            time.sleep(1)
            window.load_url(f"http://{SERVER_HOST}:{SERVER_PORT}")
        else:
            logging.error("Server timeout")
            window.load_html("<h1>Error: Server Timeout</h1>")
            
    threading.Thread(target=monitor_and_switch, daemon=True).start()

    # 5. Start UI Loop
    window.events.closed += on_closed
    webview.start(debug=True)
