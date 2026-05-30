"""
Entry point for the Secure AI Executive Assistant UI.

Run with:
    python run_ui.py

Or directly with uvicorn:
    uvicorn src.ui.app:app --reload --port 8000
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "src.ui.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
