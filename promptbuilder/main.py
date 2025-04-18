# promptbuilder/main.py
import sys
import os

# Ensure the package root is discoverable, especially when run with `python -m`
# or potentially from a PyInstaller bundle where paths can be tricky.
if __package__ is None and not hasattr(sys, "frozen"):
    # Direct execution: add project root to sys.path
    path = os.path.realpath(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(os.path.dirname(path)))

# Now perform the imports after potentially modifying sys.path
from promptbuilder.ui.application import run
from promptbuilder.services.logging import setup_logging

if __name__ == "__main__":
    setup_logging() # Configure logging early
    run(sys.argv)