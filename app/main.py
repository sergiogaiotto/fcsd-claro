import time as _time
from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.core.config import settings
from app.core.database import init_metadata_tables
from app.core.security import validate_session, can_codegen, is_admin
from app.api.routes import router as api_router, COOKIE_NAME

# Cache-buster for static JS/CSS — bumps every server restart so deployments
# of frontend changes do not get served stale by the browser cache.
STATIC_VERSION = str(int(_time.time()))

app = FastAPI(
    title="Fale com Seus Dados",
    description="Consulte seus dados usando linguagem natural e obtenha insights instantâneos. Conecte-se aos bancos de dados, explore seus dados e crie visualizações interativas sem escrever uma única linha de código.",
    version="2.1.0",
    docs_url=None,
)

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
templates = Jinja2Templates(directory=str(settings.templates_dir))

app.include_router(api_router)

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} • API Docs",
        swagger_ui_parameters={
            "docExpansion": "list",
            "defaultModelsExpandDepth": -1,
            "displayRequestDuration": True,
            "filter": True,
            "persistAuthorization": True,
            "syntaxHighlight.theme": "obsidian",
            "tryItOutEnabled": True,
        },
        swagger_css_url="/static/swagger-custom.css",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
    )


@app.get("/docs/oauth2-redirect", include_in_schema=False)
async def swagger_ui_redirect():
    return get_swagger_ui_oauth2_redirect_html()


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # Standalone HTML pages (PyGWalker, Chart.js, Analytics) load external CDNs
    # and open in new tabs — do NOT apply restrictive CSP to them.
    path = request.url.path
    standalone_prefixes = ("/api/explore", "/api/chart", "/api/analytics", "/api/gallery/")
    if not any(path.startswith(p) for p in standalone_prefixes):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://*.perplexity.ai; "
            "img-src 'self' data:; "
            "connect-src 'self' https://cdn.jsdelivr.net"
        )
    return response


PUBLIC_PATHS = {"/login", "/api/auth/login", "/api/auth/logout", "/api/auth/check", "/api/health", "/favicon.ico"}
PUBLIC_PREFIXES = ("/static/", "/api/gallery/", "/api/v1/")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)

    token = request.cookies.get(COOKIE_NAME)
    user = validate_session(token) if token else None

    if user is None:
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Não autenticado"})
        return RedirectResponse(url="/login", status_code=302)

    request.state.user = user
    return await call_next(request)


# Tracks whether the metadata schema bootstrap succeeded. If False the app
# still serves traffic (so Render's port detection works and operators can
# read the logs) but every request that touches the DB returns 503 with a
# clear message, and a background task keeps retrying init_metadata_tables.
_DB_READY = False
_DB_LAST_ERROR = ""


def _try_init_db() -> bool:
    """Best-effort metadata bootstrap. Returns True on success, False on
    failure (logs the cause). Does NOT raise — never blocks startup."""
    global _DB_READY, _DB_LAST_ERROR
    import sys
    import traceback as _tb
    try:
        init_metadata_tables()
        _DB_READY = True
        _DB_LAST_ERROR = ""
        print("[startup] DB schema initialised; app is fully ready.", file=sys.stderr, flush=True)
        return True
    except Exception as e:
        _DB_READY = False
        _DB_LAST_ERROR = f"{type(e).__name__}: {e}"
        # Mask password, then log the URL we tried.
        try:
            from app.core.config import settings
            from urllib.parse import urlsplit, urlunsplit
            parts = urlsplit(settings.database_url)
            netloc = parts.netloc
            if parts.password:
                netloc = netloc.replace(parts.password, "***", 1)
            masked = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
        except Exception:
            masked = "(could not resolve database_url)"
        print(
            f"[startup] DB init FAILED ({_DB_LAST_ERROR}). "
            f"Target: {masked}. "
            "App will keep serving — DB-backed routes return 503 until reachable. "
            "Common causes: PG host firewalls Render's egress IP, "
            "listen_addresses != '*', NAT without port-forward on 5432.",
            file=sys.stderr, flush=True,
        )
        print(_tb.format_exc(), file=sys.stderr, flush=True)
        return False


async def _db_init_retry_loop():
    """Background task: re-tries DB bootstrap every 30 s until it succeeds.
    Then exits."""
    import asyncio
    import sys
    while not _DB_READY:
        await asyncio.sleep(30)
        print("[startup] retrying DB init…", file=sys.stderr, flush=True)
        if _try_init_db():
            break


@app.on_event("startup")
async def startup():
    """Boot the app even when the DB is unreachable.

    Render's port-binding detector needs uvicorn to start serving on 8000
    quickly; a failing init_metadata_tables() that raises kills the worker
    before the port is open, the deploy fails, and operators never get to
    read the logs. Here we attempt the bootstrap, catch any exception,
    expose it on /api/health, and keep retrying in the background.
    """
    import asyncio
    if not _try_init_db():
        # Don't block startup — schedule a background retry loop so the app
        # heals automatically once the DB becomes reachable.
        asyncio.create_task(_db_init_retry_loop())


@app.on_event("shutdown")
async def shutdown():
    """Drain the psycopg connection pool when the process exits, so
    in-flight conns are returned cleanly instead of being killed by the
    Postgres server's idle reaper."""
    try:
        from app.core.db_engine import close_pool
        close_pool()
    except Exception:
        pass


@app.get("/api/health", include_in_schema=False)
async def health():
    """Simple health endpoint that never touches the DB. Render uses this
    to confirm the port is bound, and operators can curl it to inspect
    DB readiness without scrolling the logs."""
    from fastapi.responses import JSONResponse
    return JSONResponse({
        "status": "ok",
        "db_ready": _DB_READY,
        "db_last_error": _DB_LAST_ERROR or None,
    })


# Favicon SVG inline — evita o 404 de /favicon.ico (todo navegador o requisita).
# Quadrado vermelho Claro com o ícone </> (codegen/copiloto).
_FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<rect width='32' height='32' rx='7' fill='#e30613'/>"
    "<path d='M13 11l-4 5 4 5M19 11l4 5-4 5' fill='none' stroke='#fff' "
    "stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'/></svg>"
)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if token and validate_session(token):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html") # return templates.TemplateResponse("login.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "default.html", {"static_v": STATIC_VERSION})


@app.get("/codegen", response_class=HTMLResponse)
async def codegen_page(request: Request):
    """TDIA-CodeGen — página própria do módulo (Root/Admin/Engenheiro de Dados).
    O auth_middleware já garante sessão válida; aqui restringimos por papel."""
    user = getattr(request.state, "user", None)
    if not user or not can_codegen(user):
        return RedirectResponse(url="/", status_code=302)
    _role_labels = {
        "root": "Root", "superuser": "Super Usuário", "admin": "Administrador",
        "analista": "Analista", "engenheiro_dados": "Engenheiro de Dados", "user": "Usuário",
    }
    return templates.TemplateResponse(request, "codegen/index.html", {
        "static_v": STATIC_VERSION,
        "user": user,
        "user_type_label": _role_labels.get(user.get("user_type"), user.get("user_type")),
        "is_admin": is_admin(user),
    })
