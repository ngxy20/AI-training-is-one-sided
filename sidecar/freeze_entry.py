"""PyInstaller entry point for the standalone sidecar executable.

Build (from the sidecar/ directory):
  python -m PyInstaller --noconfirm --clean --onedir --name aixian-sidecar ...
"""
from aixian.__main__ import main

if __name__ == "__main__":
    main()
