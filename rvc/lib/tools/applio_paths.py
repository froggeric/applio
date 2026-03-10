"""
Applio Paths - Centralized path resolution for macOS native app.

Handles path resolution for:
- Process state file (active_processes.json)
- Process history file (process_history.json)
- User data directory
- Log files
"""

import os
from typing import Optional


class ApplioPaths:
    """Centralized path management for Applio macOS app."""
    
    @staticmethod
    def get_data_path() -> str:
        """Get user's data storage location.
        
        Checks in order:
        1. APPLIO_DATA_PATH environment variable
        2. NSUserDefaults preference (macOS)
        3. Default ~/Applio
        """
        # Check environment variable first
        data_path = os.environ.get("APPLIO_DATA_PATH")
        if data_path:
            return data_path
        
        # Check NSUserDefaults (macOS)
        try:
            from Foundation import NSUserDefaults
            defaults = NSUserDefaults.standardUserDefaults()
            data_path = defaults.stringForKey_("dataPath")
            if data_path:
                return data_path
        except ImportError:
            pass
        
        # Default
        return os.path.expanduser("~/Applio")
    
    @staticmethod
    def get_state_dir() -> str:
        """Get directory for process state files."""
        return os.path.join(ApplioPaths.get_data_path(), ".applio")
    
    @staticmethod
    def get_state_file() -> str:
        """Get path to active_processes.json."""
        return os.path.join(ApplioPaths.get_state_dir(), "active_processes.json")
    
    @staticmethod
    def get_history_file() -> str:
        """Get path to process_history.json."""
        return os.path.join(ApplioPaths.get_state_dir(), "process_history.json")
    
    @staticmethod
    def get_logs_dir() -> str:
        """Get user's logs directory (training outputs)."""
        return os.path.join(ApplioPaths.get_data_path(), "logs")
    
    @staticmethod
    def get_launcher_log_dir() -> str:
        """Get system log directory for launcher."""
        return os.path.expanduser("~/Library/Logs/Applio")
    
    @staticmethod
    def get_runtime_config_file() -> str:
        """Get path to runtime_paths.json."""
        # Prefer Application Support location
        app_support = os.path.expanduser("~/Library/Application Support/Applio")
        return os.path.join(app_support, "runtime_paths.json")
    
    @staticmethod
    def ensure_state_dir() -> bool:
        """Ensure state directory exists.
        
        Returns:
            True if directory exists or was created, False on error.
        """
        try:
            os.makedirs(ApplioPaths.get_state_dir(), exist_ok=True)
            return True
        except OSError as e:
            import logging
            logging.warning(f"[ApplioPaths] Could not create state directory: {e}")
            return False


# Module-level convenience functions
def get_data_path() -> str:
    return ApplioPaths.get_data_path()


def get_state_file() -> str:
    return ApplioPaths.get_state_file()


def get_history_file() -> str:
    return ApplioPaths.get_history_file()
