"""Login for the dashboard: log in / log out / who am I, plus the guard that protects every other page.

How it works (simple version):
  1. The login page sends username + password to POST /api/login.
  2. If they match the saved hash, the server makes a long random "ticket" (session token), remembers it,
     and gives it to the browser as a cookie the page's JavaScript cannot read (HttpOnly).
  3. The browser sends that cookie with every request; the guard lets it through only if the ticket is known
     and not expired. No ticket → API answers 401, pages redirect to login.html.
Tickets are kept in memory, so restarting the server logs everyone out (fine for a demo).
"""

import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from engine import config
from engine.create_users import check_password

router = APIRouter(prefix="/api", tags=["login"])

SESSIONS = {}   # token → (username, expiry time in seconds)

# Reachable without logging in: the login page itself, its style/scripts, the health check,
# and the files that make the site installable as an app (manifest, service worker, icons).
OPEN_PATHS = {"/api/login", "/api/health", "/login.html", "/manifest.webmanifest", "/sw.js"}
OPEN_PREFIXES = ("/css/", "/js/", "/icons/")


class LoginRequest(BaseModel):
    username: str
    password: str


def current_user(request):
    """The logged-in username for this request, or None."""
    token = request.cookies.get(config.SESSION_COOKIE)
    session = SESSIONS.get(token) if token else None
    if session is None:
        return None
    username, expires = session
    if time.time() > expires:
        SESSIONS.pop(token, None)   # expired ticket: forget it
        return None
    return username


@router.post("/login")
def login(body: LoginRequest, response: Response):
    """Check the password; on success give the browser a session cookie."""
    if not check_password(body.username.strip(), body.password):
        time.sleep(config.FAILED_LOGIN_DELAY_S)
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = (body.username.strip(), time.time() + config.SESSION_HOURS * 3600)
    response.set_cookie(config.SESSION_COOKIE, token, max_age=config.SESSION_HOURS * 3600,
                        httponly=True, samesite="lax")
    return {"username": body.username.strip()}


@router.post("/logout")
def logout(request: Request, response: Response):
    """Forget this browser's ticket and delete the cookie."""
    SESSIONS.pop(request.cookies.get(config.SESSION_COOKIE), None)
    response.delete_cookie(config.SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    """Who is logged in (the top bar shows this name)."""
    username = current_user(request)
    if username is None:
        raise HTTPException(status_code=401, detail="Please log in.")
    return {"username": username}


async def require_login(request: Request, call_next):
    """Guard in front of every request: open paths pass, everything else needs a valid session."""
    path = request.url.path
    if path in OPEN_PATHS or path.startswith(OPEN_PREFIXES) or current_user(request):
        response = await call_next(request)
        if path.endswith(".html") or path == "/":
            response.headers["Cache-Control"] = "no-store"   # Back button after logout must not show data
        elif path.endswith((".js", ".css")):
            response.headers["Cache-Control"] = "no-cache"   # always ask the server, so code changes show up at once
        return response
    if path.startswith("/api/"):
        return JSONResponse({"detail": "Please log in."}, status_code=401)
    page = path.lstrip("/") or "index.html"
    return RedirectResponse(f"login.html?next={page}", status_code=303)
