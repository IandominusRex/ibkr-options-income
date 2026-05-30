"""Entry point for the long-running Telegram approval service.

Usage:
    python -m scripts.run_approval_service
    # or run as a systemd service / background process
"""

from src.notify.approval_service import main

main()
