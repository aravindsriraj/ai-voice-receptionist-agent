from __future__ import annotations
import logging
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse

logger = logging.getLogger(__name__)


def make_router(get_store, get_twilio, settings, static_dir) -> APIRouter:
    router = APIRouter()
    static = Path(static_dir)

    def current_user(request: Request):
        email = request.session.get("user_email")
        return get_store().get(email) if email else None

    @router.get("/")
    async def index(request: Request):
        return RedirectResponse("/app" if request.session.get("user_email") else "/login")

    @router.get("/login")
    async def login_page():
        return FileResponse(static / "login.html")

    @router.get("/register")
    async def register_page():
        return FileResponse(static / "register.html")

    @router.get("/app")
    async def app_page(request: Request):
        if not request.session.get("user_email"):
            return RedirectResponse("/login", status_code=303)
        return FileResponse(static / "app.html")

    @router.post("/register")
    async def register(request: Request):
        f = await request.form()
        try:
            user = get_store().register(
                f.get("name", ""), f.get("email", ""), f.get("password", ""),
                f.get("country_code", ""), f.get("mobile", ""))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        request.session["user_email"] = user["email"]
        return RedirectResponse("/app", status_code=303)

    @router.post("/login")
    async def login(request: Request):
        f = await request.form()
        user = get_store().authenticate(f.get("email", ""), f.get("password", ""))
        if not user:
            return JSONResponse({"error": "invalid email or password"}, status_code=401)
        request.session["user_email"] = user["email"]
        return RedirectResponse("/app", status_code=303)

    @router.post("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @router.get("/api/me")
    async def me(request: Request):
        user = current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="not logged in")
        return {"name": user["name"], "email": user["email"], "mobile": user["mobile"]}

    @router.post("/api/call-me")
    async def call_me(request: Request):
        user = current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="not logged in")
        base = settings.public_base_url.rstrip("/")
        try:
            call = get_twilio().calls.create(
                to=user["mobile"], from_=settings.twilio_caller_number,
                url=f"{base}/voice", method="POST")
        except Exception as e:
            logger.warning("call-me failed for %s: %s", user["mobile"], e)
            msg = "We couldn't place the call."
            if "unverified" in str(e).lower() or "not verified" in str(e).lower():
                msg = ("This number isn't verified for calling yet. On our current phone "
                       "plan we can only call verified numbers — try the browser instead.")
            return JSONResponse({"error": msg}, status_code=502)
        return {"sid": call.sid, "status": call.status, "to": user["mobile"]}

    return router
