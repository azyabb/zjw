import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

from config import settings
from database import cosmos_db
from routes_auth import router as auth_router
from routes_media import router as media_router
from storage import blob_storage

# Setup logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
app_logger = logging.getLogger(__name__)


@asynccontextmanager
async def application_lifespan(application: FastAPI):
    """Manage application startup and shutdown lifecycle"""
    # Application startup phase
    app_logger.info("Initializing Cloud Media Platform API...")
    try:
        cosmos_db.initialize()
        blob_storage.initialize()
        app_logger.info("All Azure services are ready")
    except Exception as error:
        app_logger.error(f"Azure services initialization failed: {error}")
        raise

    yield

    # Application shutdown phase
    app_logger.info("Terminating Cloud Media Platform API...")


# Initialize FastAPI application instance
app = FastAPI(
    title="Cloud Media Platform API",
    version="1.0.0",
    description="REST API for cloud-based media storage and management",
    lifespan=application_lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url="/api/redoc"
)

# Apply CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=settings.allowed_origins_list,
    allow_headers=["*"],
    allow_methods=["*"]
)


# Custom exception handlers
@app.exception_handler(RequestValidationError)
async def handle_validation_error(req: Request, validation_err: RequestValidationError):
    """Process request validation errors"""
    return JSONResponse(
        content={
            "error": {
                "message": "Invalid request data",
                "code": "VALIDATION_ERROR",
                "details": str(validation_err)
            }
        },
        status_code=status.HTTP_400_BAD_REQUEST
    )


@app.exception_handler(Exception)
async def handle_general_error(req: Request, error: Exception):
    """Process unexpected exceptions"""
    app_logger.error(f"Unexpected error occurred: {error}", exc_info=True)
    error_details = str(error) if settings.api_host == "0.0.0.0" else None
    return JSONResponse(
        content={
            "error": {
                "message": "An unexpected error occurred",
                "code": "INTERNAL_SERVER_ERROR",
                "details": error_details
            }
        },
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )


# API health monitoring endpoint
@app.get("/api/health", tags=["Health"])
async def check_service_health():
    """Monitor API service status"""
    return {
        "service": "Cloud Media Platform API",
        "status": "healthy",
        "version": "1.0.0"
    }


# Register API route modules
app.include_router(auth_router, prefix="/api")
app.include_router(media_router, prefix="/api")

# Frontend static file serving configuration
frontend_static_path = Path(__file__).parent / "static"
if frontend_static_path.exists():
    # Root endpoint serves main page
    @app.get("/", tags=["Frontend"])
    async def deliver_main_page():
        """Deliver primary Angular application page"""
        return FileResponse(frontend_static_path / "index.html")

    # Wildcard route for SPA navigation (must be defined last)
    @app.get("/{resource_path:path}", tags=["Frontend"])
    async def deliver_spa_resource(resource_path: str):
        """Handle SPA routing and static resources"""
        # Reject requests to non-existent API endpoints
        if resource_path.startswith("api/"):
            return JSONResponse(
                content={"error": {"message": "Endpoint not found", "code": "NOT_FOUND"}},
                status_code=status.HTTP_404_NOT_FOUND
            )

        # Serve static file if it exists
        static_file = frontend_static_path / resource_path
        if static_file.is_file():
            return FileResponse(static_file)

        # Default to index.html for client-side routing
        return FileResponse(frontend_static_path / "index.html")
else:
    # Default endpoint when static files are not available
    @app.get("/", tags=["Root"])
    async def api_root():
        """API information endpoint"""
        return {
            "docs": "/api/docs",
            "message": "Cloud Media Platform API",
            "version": "1.0.0"
        }


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        reload=True,
        host=settings.api_host,
        log_level="info",
        port=settings.api_port
    )
