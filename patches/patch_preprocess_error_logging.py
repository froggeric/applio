#!/usr/bin/env python3
"""
Patcher to add file-based error logging to preprocessing.

Bug: Exception handling in preprocess.py just prints to stdout, which gets
lost in multiprocessing spawn mode. Errors are silently swallowed.

Fix: Add file-based logging so preprocessing errors are persisted and can
be diagnosed after the fact.

Applied at build time by build_macos.py.
"""

import os
import re


def patch_preprocess_py(base_path: str) -> bool:
    """Patch rvc/train/preprocess/preprocess.py to log errors to file."""
    preprocess_py_path = os.path.join(base_path, "preprocess.py")

    if not os.path.exists(preprocess_py_path):
        print(
            f"[patch_preprocess_error_logging] preprocess.py not found at {preprocess_py_path}"
        )
        return False

    with open(preprocess_py_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Idempotency check
    if "_PREPROCESS_ERROR_LOGGING_PATCHED" in content:
        print(f"[patch_preprocess_error_logging] preprocess.py already patched")
        return True

    patched = False

    # Pattern: The silent exception handler (8-space indentation)
    # Original:
    #         except Exception as error:
    #             print(f"Error processing audio: {error}")
    #
    # Patched: Add file-based logging before the print

    old_pattern = r"""        except Exception as error:
            print\(f"Error processing audio: \{error\}"\)"""

    new_code = """        except Exception as error:
            # Log to file for debugging (persists across multiprocessing spawn)
            import datetime
            error_log_path = os.path.expanduser("~/Library/Logs/Applio/preprocess_errors.log")
            try:
                os.makedirs(os.path.dirname(error_log_path), exist_ok=True)
                with open(error_log_path, "a") as error_log:
                    error_log.write(f"[{datetime.datetime.now().isoformat()}] {path}: {error}" + chr(10))
            except IOError:
                pass  # Can't log if logging fails
            print(f"Error processing audio: {error}")"""

    if re.search(old_pattern, content):
        content = re.sub(old_pattern, new_code, content)
        print(f"[patch_preprocess_error_logging] Added file-based error logging")
        patched = True

    if patched:
        # Add idempotency marker
        content = "# _PREPROCESS_ERROR_LOGGING_PATCHED = True\n" + content

        with open(preprocess_py_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True

    print(f"[patch_preprocess_error_logging] No patterns found in preprocess.py")
    return False


if __name__ == "__main__":
    import sys

    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_preprocess_py(base_path)
    sys.exit(0 if success else 1)
