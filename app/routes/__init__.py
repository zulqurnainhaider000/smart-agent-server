"""Routes package."""
from app.routes.health import health_bp
from app.routes.agent import agent_bp

__all__ = ["health_bp", "agent_bp"]
