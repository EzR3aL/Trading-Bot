"""Dashboard module - Web UI and API."""

def run_dashboard(host: str = "0.0.0.0", port: int = 8080):
    """Start the web dashboard."""
    import uvicorn
    from src.api.main_app import app

    uvicorn.run(app, host=host, port=port)
