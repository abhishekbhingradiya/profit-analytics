from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR
from app.security import get_csrf_token

NAV_ITEMS = [
    ("dashboard", "Overview", "/dashboard"),
    ("products", "Products & sales", "/products"),
    ("customers", "Customers", "/customers"),
    ("billing", "Billing & payments", "/billing"),
    ("analytics", "Analytics & forecast", "/analytics"),
    ("notifications", "Notifications", "/notifications"),
]

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.globals["csrf_token"] = get_csrf_token
templates.env.globals["nav_items"] = NAV_ITEMS


def render(request: Request, name: str, status_code: int = 200, **context):
    context.setdefault("user", None)
    context.setdefault("unread", 0)
    context.setdefault("flash", request.session.pop("flash", None))
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def flash(request: Request, kind: str, text: str) -> None:
    request.session["flash"] = {"kind": kind, "text": text}
