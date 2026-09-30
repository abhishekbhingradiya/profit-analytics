from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(db: Session, user: User, action: str, detail: str = "") -> None:
    db.add(AuditLog(org_id=user.org_id, user_id=user.id, action=action, detail=detail[:1000]))
