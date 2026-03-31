#!/usr/bin/env python3
"""ae-console: Launch Streamlit management UI."""

import os
import subprocess
import sys


def main():
    script_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "ae-console.py")
    script_path = os.path.normpath(script_path)

    if not os.path.exists(script_path):
        # Fallback: find via package installation
        script_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "..", "scripts", "ae-console.py",
        )
        script_path = os.path.normpath(script_path)

    sys.exit(subprocess.call(["streamlit", "run", "--server.address", "localhost", script_path] + sys.argv[1:]))


if __name__ == "__main__":
    main()
