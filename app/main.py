# Copyright 2024
# Directory: yt-rag/app/main.py

"""
FastAPI application for RAG (Retrieval-Augmented Generation) backend.
Provides endpoints for document seeding and question answering with citations.
"""

import hmac
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlsplit
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, Response, JSONResponse

from .core import admin_session
from .core.config import get_settings
from .core.database import db
from .models.requests import SeedRequest, AnswerRequest
from .models.responses import SeedResponse, AnswerResponse, HealthResponse
from .services.rag import rag_service
from .data.default_documents import DEFAULT_DOCUMENTS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()

_seed_bearer = HTTPBearer(auto_error=False)

# Admin pages and their redirects are never cached, so signing out or a session
# ending always shows in the browser.
_NO_STORE = {"Cache-Control": "no-store"}


def _is_seed_token(provided: str, expected: str) -> bool:
    """Whether `provided` is the admin token, compared as UTF-8 bytes in constant time."""
    try:
        provided_bytes = provided.encode()
    except UnicodeEncodeError:  # e.g. a lone surrogate from a JSON body: never the token
        return False
    return hmac.compare_digest(provided_bytes, expected.encode())


def _has_admin_session(request: Request, token: str) -> bool:
    """Whether the request carries a valid admin session cookie for `token`."""
    value = request.cookies.get(admin_session.COOKIE_NAME)
    return admin_session.is_valid(value, token, time.time())


def admin_signed_in(request: Request) -> bool:
    """Whether the request may use the admin page.

    True when no token is configured (local development), or when the request
    carries a valid admin session for SEED_TOKEN.
    """
    token = settings.seed_token
    if not token:
        return True
    return _has_admin_session(request, token)


def _origin_is_this_site(request: Request) -> bool:
    """Whether the request's Origin names the host the request was sent to.

    Hosts are compared, not schemes: behind the hosting proxy the app sees http
    while browsers send https. A missing Origin or "Origin: null" doesn't match.
    """
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    if not origin or not host:
        return False
    try:
        origin_host = urlsplit(origin).netloc
    except ValueError:  # e.g. a malformed IPv6 address
        return False
    return bool(origin_host) and origin_host == host


async def require_seed_access(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_seed_bearer),
) -> None:
    """Reject /seed requests from anyone but the admin, when SEED_TOKEN is configured.

    The admin is a request with "Authorization: Bearer <SEED_TOKEN>", or one from
    the signed-in admin page: a valid session cookie, sent from this site.
    """
    expected = settings.seed_token
    if not expected:
        return  # no token configured: /seed stays open (local development)
    provided = credentials.credentials if credentials else ""
    if _is_seed_token(provided, expected):
        return
    if _origin_is_this_site(request) and _has_admin_session(request, expected):
        return
    raise HTTPException(
        status_code=401,
        detail="Missing or invalid admin token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def warn_if_seed_unprotected() -> None:
    """Log a warning when a production deployment leaves /seed open."""
    if settings.environment == "production" and not settings.seed_token:
        logger.warning("SEED_TOKEN is not set: anyone can overwrite the knowledge base via POST /seed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Starting RAG API application")
    warn_if_seed_unprotected()

    try:
        # Initialize database connection
        await db.connect()
        
        # Check database schema
        await db.initialize_schema()
        
        logger.info("Application startup completed successfully")
        
    except Exception as e:
        logger.error(f"Application startup failed: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down RAG API application")
    await db.disconnect()


# Create FastAPI application
app = FastAPI(
    title="RAG AI Agent Backend",
    description="A minimal, production-ready FastAPI backend demonstrating Retrieval-Augmented Generation (RAG) with vector similarity search.",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # NextJS default
        "http://localhost:3001",  # Alternative port
        "https://yt-rag.vercel.app",  # Production frontend
        "*"  # Allow all for development (remove in production)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for the chat interface
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/chat", tags=["General"])
async def chat_interface():
    """Serve the chat interface."""
    return FileResponse("static/chat.html")


@app.get("/admin", include_in_schema=False)
async def admin_interface(request: Request):
    """Serve the knowledge base admin page to the signed-in admin.

    Without a valid admin session (when SEED_TOKEN is configured) this answers 303
    to the sign-in page /admin/login. Neither answer is cached.
    """
    if admin_signed_in(request):
        return FileResponse("static/admin.html", headers=_NO_STORE)
    return RedirectResponse("/admin/login", status_code=303, headers=_NO_STORE)


@app.get("/admin/login", include_in_schema=False)
async def admin_login_page(request: Request):
    """Serve the admin sign-in page, or send a signed-in admin on to /admin.

    With no token configured there is nothing to sign in to, so this also answers
    303 to /admin. Neither answer is cached.
    """
    if admin_signed_in(request):
        return RedirectResponse("/admin", status_code=303, headers=_NO_STORE)
    return FileResponse("static/admin-login.html", headers=_NO_STORE)


@app.post("/admin/login", include_in_schema=False)
async def admin_sign_in(request: Request):
    """Start an admin session for the body {"token": "<SEED_TOKEN>"}.

    204 with the session cookie on the right token; 401 on anything else, with no
    cookie. The body is read by hand, so a bad body is a 401 and never echoed back
    (a pydantic body would answer 422 with the input). With no token configured,
    answers 204 without a cookie: the admin page is open anyway.
    """
    expected = settings.seed_token
    if not expected:
        return Response(status_code=204)
    try:
        body = await request.json()
    except ValueError:  # not JSON, or not UTF-8
        body = None
    provided = body.get("token") if isinstance(body, dict) else None
    if not isinstance(provided, str) or not _is_seed_token(provided, expected):
        logger.warning("Admin sign-in failed")  # never the body or the token
        return JSONResponse(status_code=401, content={"detail": "Admin token rejected"})
    response = Response(status_code=204)
    response.set_cookie(
        admin_session.COOKIE_NAME,
        admin_session.issue(expected, time.time()),
        max_age=admin_session.SESSION_SECONDS,
        path="/",
        secure=settings.environment == "production",
        httponly=True,
        samesite="strict",
    )
    return response


@app.post("/admin/logout", include_in_schema=False)
async def admin_sign_out():
    """End the admin session in this browser by deleting its cookie (204 either way)."""
    response = Response(status_code=204)
    response.delete_cookie(
        admin_session.COOKIE_NAME,
        path="/",
        secure=settings.environment == "production",
        httponly=True,
        samesite="strict",
    )
    return response


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Handle favicon requests to prevent 404 errors."""
    return Response(status_code=204)  # No Content


@app.get("/", tags=["General"])
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Welcome to RAG AI Agent Backend",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "health": "/healthz",
            "seed": "/seed",
            "answer": "/answer",
            "documents": "/documents",
            "greet": "/greet/{name}"
        }
    }


@app.get("/greet/{name}", tags=["General"])
async def greet(name: str):
    """
    Greet endpoint that returns a personalized greeting.
    
    Args:
        name (str): Name of the person to greet
        
    Returns:
        Personalized greeting message
    """
    return {"message": f"Hello, {name}! I think you are great!"}


@app.get("/healthz", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint with database connectivity test."""
    try:
        # Test database connection
        db_healthy = await db.health_check()
        
        return HealthResponse(
            status="ok" if db_healthy else "degraded",
            database_connected=db_healthy
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Service unavailable: {str(e)}"
        )


@app.get("/documents", tags=["General"])
async def get_documents():
    """
    Get the default documents used for seeding the knowledge base.
    
    Returns:
        List of default documents with their chunk_id, source, and text
    """
    return {"documents": DEFAULT_DOCUMENTS}


@app.post(
    "/seed",
    response_model=SeedResponse,
    tags=["RAG"],
    dependencies=[Depends(require_seed_access)],
)
async def seed_documents(request: SeedRequest = SeedRequest()):
    """
    Replace the knowledge base with documents.

    If no documents are provided (or an empty list), seeds the default profile documents.
    Documents are chunked, embedded, and stored in the vector database; after
    they're saved, every chunk this seed didn't include is deleted. The response
    reports both counts.
    When SEED_TOKEN is set, requires "Authorization: Bearer <SEED_TOKEN>", or the
    signed-in admin session sent from this site (the admin page).
    """
    try:
        logger.info("Starting document seeding process")
        
        # Convert request documents to the format expected by RAG service
        documents = None
        if request.docs:
            documents = [
                {
                    'chunk_id': doc.chunk_id,
                    'source': doc.source,
                    'text': doc.text
                }
                for doc in request.docs
            ]
        
        # Process documents through RAG pipeline
        result = await rag_service.seed_documents(documents)

        logger.info(f"Seeding completed: {result.inserted} chunks inserted, {result.removed} removed")

        return SeedResponse(inserted=result.inserted, removed=result.removed)
        
    except Exception as e:
        logger.error(f"Seeding failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to seed documents: {str(e)}"
        )


@app.post("/answer", response_model=AnswerResponse, tags=["RAG"])
async def answer_question(request: AnswerRequest):
    """
    Answer a question using RAG (Retrieval-Augmented Generation).
    
    Pipeline:
    1. Embed the query
    2. Vector similarity search to find relevant chunks
    3. Generate answer using LLM with context
    4. Return answer with citations and debug info
    """
    try:
        logger.info(f"Processing query: '{request.query[:100]}...'")
        
        # Process query through RAG pipeline
        result = await rag_service.answer_query(
            query=request.query,
            top_k=request.top_k
        )
        
        # Convert to response model
        response = AnswerResponse(
            text=result['text'],
            citations=result['citations'],
            sources=result.get('sources', []),
            debug={
                'top_doc_ids': result['debug']['top_doc_ids'],
                'latency_ms': result['debug']['latency_ms'],
                'answer_mode': result['debug']['answer_mode'],
            }
        )
        
        logger.info(f"Query processed successfully in {result['debug']['latency_ms']}ms")
        
        return response
        
    except Exception as e:
        logger.error(f"Query processing failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process query: {str(e)}"
        )


# Error handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors."""
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "detail": "The requested endpoint does not exist",
            "available_endpoints": ["/", "/healthz", "/seed", "/answer", "/docs"]
        }
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "detail": "An unexpected error occurred. Please check the logs."
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
