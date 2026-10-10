"""Login sessions (working hours / online status) and the audit log."""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import AuditLog, LoginSession, User

TOUCH_EVERY = timedelta(seconds=60)


def client_info(request) -> tuple:
    if request is None:
        return None, None
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else None)
    return ip, (request.headers.get("user-agent") or "")[:300]


def start_session(db: Session, user: User, method: str, request=None) -> int:
    from app.services import settings_store as st
    idle = timedelta(minutes=st.get_float("idle_session_minutes") or 30)
    now = datetime.utcnow()
    # Close this user's stale open sessions so hours aren't double counted
    for s in db.query(LoginSession).filter(LoginSession.user_id == user.id, LoginSession.logout_at.is_(None)).all():
        if now - (s.last_seen_at or s.login_at) > idle:
            s.logout_at = s.last_seen_at or s.login_at
    ip, ua = client_info(request)
    s = LoginSession(user_id=user.id, role=user.role.value, method=method, ip=ip, user_agent=ua,
                     login_at=now, last_seen_at=now)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s.id


def touch(db: Session, sid: Optional[int], user_id: int):
    if not sid:
        return
    s = db.query(LoginSession).filter(LoginSession.id == sid, LoginSession.user_id == user_id).first()
    if not s or s.logout_at:
        return
    now = datetime.utcnow()
    if not s.last_seen_at or now - s.last_seen_at > TOUCH_EVERY:
        s.last_seen_at = now
        db.commit()


def end_session(db: Session, sid: Optional[int], user_id: int):
    if not sid:
        return
    s = db.query(LoginSession).filter(LoginSession.id == sid, LoginSession.user_id == user_id).first()
    if s and not s.logout_at:
        s.logout_at = datetime.utcnow()
        s.last_seen_at = s.logout_at
        db.commit()


def session_minutes(s: LoginSession, now: Optional[datetime] = None, idle_minutes: float = 30) -> float:
    """Worked minutes for a session: login → logout, or → last activity for open/abandoned sessions."""
    now = now or datetime.utcnow()
    end = s.logout_at or s.last_seen_at or s.login_at
    if not s.logout_at and now - (s.last_seen_at or s.login_at) <= timedelta(minutes=idle_minutes):
        end = now  # still active
    return max((end - s.login_at).total_seconds() / 60.0, 0.0)


def audit(db: Session, user: Optional[User], action: str, target: str = None, details: str = None, commit: bool = True):
    db.add(AuditLog(user_id=user.id if user else None, user_name=user.full_name if user else "System",
                    role=user.role.value if user else None, action=action, target=target,
                    details=(details or "")[:2000] or None))
    if commit:
        db.commit()
