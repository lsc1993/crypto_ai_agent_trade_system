from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_exception_handlers
from app.api.router import API_NAME
from app.api.router import router as api_router
from app.api.routes.health import router as health_router
from app.shared.config import AppSettings
from app.shared.logging import configure_logging


def create_app() -> FastAPI:
    settings = AppSettings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=API_NAME,
        version="0.1.0",
    )
    install_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type"],
    )
    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()
