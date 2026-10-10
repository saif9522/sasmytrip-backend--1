"""
Team activity, agent management and platform settings.

  POST /api/activity/ping              any logged-in user — keeps "online" status fresh
  POST /api/activity/logout            ends the current login session
  GET  /api/activity/my-sessions       own login history

  GET  /api/admin/team/online          who is online now
  GET  /api/admin/team/summary         per person: hours worked, sessions, first login, last seen, bookings, actions
  GET  /api/admin/team/sessions        login history (filter by user / days)
  GET  /api/admin/audit                action log (filter by user / action / days)

  GET  /api/admin/agents               agents with business stats
  GET  /api/admin/agents/{id}          one agent: bookings + login history
  PUT  /api/admin/agents/{id}          approve / suspend / set commission %

  GET  /api/settings/public            company name & support contact (for the website footer)
  GET  /api/admin/settings             all settings with labels
  PUT  /api/admin/settings             update (Super Admin)
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import ALGORITHM, SECRET_KEY, get_current_user, oauth2_scheme, require_roles
from app.database import get_db
from app.models.models import (
    AppSetting, AuditLog, LoginSession, Notification, SupplierBooking, SupplierBookingStatus, User, UserRole,
)
from app.services import settings_store as st
from app.services.activity import audit, end_session, session_minutes

activity_router = APIRouter(prefix="/api/activity", tags=["Activity"])
admin_router = APIRouter(prefix="/api/admin", tags=["Admin — team, agents, settings"])
public_router = APIRouter(prefix="/api/settings", tags=["Settings"])

staff = require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN)
super_only = require_roles(UserRole.SUPER_ADMIN)
IST = timezone(timedelta(hours=5, minutes=30))
STAFF_ROLES = [UserRole.ADMIN, UserRole.SUPER_ADMIN]


def _sid(token: str = Depends(oauth2_scheme)) -> Optional[int]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]).get("sid")
    except JWTError:
        return None


def _since(days: int) -> datetime:
    """Start of the window in UTC. days=1 means 'today' (IST midnight)."""
    ist_midnight = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    start = ist_midnight - timedelta(days=max(days, 1) - 1)
    return start.astimezone(timezone.utc).replace(tzinfo=None)


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def _online_ids(db: Session) -> set:
    cutoff = datetime.utcnow() - timedelta(minutes=st.get_float("online_window_minutes") or 5)
    rows = db.query(LoginSession.user_id).filter(LoginSession.logout_at.is_(None), LoginSession.last_seen_at >= cutoff).distinct()
    return {r[0] for r in rows}


def _session_out(s: LoginSession, idle: float) -> dict:
    return {"id": s.id, "user_id": s.user_id, "role": s.role, "method": s.method, "ip": s.ip,
            "device": _device(s.user_agent), "login_at": _iso(s.login_at), "last_seen_at": _iso(s.last_seen_at),
            "logout_at": _iso(s.logout_at), "minutes": round(session_minutes(s, idle_minutes=idle), 1),
            "active": s.logout_at is None and datetime.utcnow() - (s.last_seen_at or s.login_at) <= timedelta(minutes=idle)}


def _device(ua: Optional[str]) -> str:
    ua = (ua or "").lower()
    if not ua:
        return "—"
    os_ = "Android" if "android" in ua else "iPhone" if "iphone" in ua else "Windows" if "windows" in ua else "Mac" if "mac os" in ua else "Linux" if "linux" in ua else "Other"
    br = "Edge" if "edg/" in ua else "Chrome" if "chrome" in ua else "Firefox" if "firefox" in ua else "Safari" if "safari" in ua else "Browser"
    return f"{br} · {os_}"


# ------------------------------------------------------------------ own activity

@activity_router.post("/ping", summary="Heartbeat — keeps online status fresh")
def ping(user: User = Depends(get_current_user)):
    return {"ok": True}


@activity_router.post("/logout", summary="End the current login session")
def logout(sid: Optional[int] = Depends(_sid), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    end_session(db, sid, user.id)
    return {"ok": True}


@activity_router.get("/my-sessions", summary="My login history")
def my_sessions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    idle = st.get_float("idle_session_minutes") or 30
    rows = db.query(LoginSession).filter(LoginSession.user_id == user.id).order_by(LoginSession.login_at.desc()).limit(30).all()
    return [_session_out(s, idle) for s in rows]


# ------------------------------------------------------------------ team (admin)

@admin_router.get("/team/online", summary="Who is online now", dependencies=[Depends(staff)])
def team_online(db: Session = Depends(get_db)):
    ids = _online_ids(db)
    users = db.query(User).filter(User.id.in_(ids)).all() if ids else []
    return [{"id": u.id, "name": u.full_name, "role": u.role.value, "company": u.company_name} for u in users]


@admin_router.get("/team/summary", summary="Hours worked & work done per person", dependencies=[Depends(staff)])
def team_summary(days: int = Query(1, ge=1, le=90), group: str = Query("staff", pattern="^(staff|agents|all)$"),
                 db: Session = Depends(get_db)):
    since = _since(days)
    idle = st.get_float("idle_session_minutes") or 30
    roles = STAFF_ROLES if group == "staff" else [UserRole.AGENT] if group == "agents" else STAFF_ROLES + [UserRole.AGENT]
    users = db.query(User).filter(User.role.in_(roles)).order_by(User.full_name).all()
    online = _online_ids(db)
    out = []
    for u in users:
        sess = db.query(LoginSession).filter(LoginSession.user_id == u.id, LoginSession.login_at >= since).all()
        last = db.query(func.max(LoginSession.last_seen_at)).filter(LoginSession.user_id == u.id).scalar()
        bookings = db.query(SupplierBooking).filter(SupplierBooking.customer_id == u.id, SupplierBooking.created_at >= since).all()
        confirmed = [b for b in bookings if b.status == SupplierBookingStatus.CONFIRMED]
        actions = db.query(func.count(AuditLog.id)).filter(AuditLog.user_id == u.id, AuditLog.created_at >= since).scalar()
        out.append({
            "id": u.id, "name": u.full_name, "email": u.email, "phone": u.phone, "role": u.role.value,
            "company": u.company_name, "is_active": u.is_active, "is_verified": u.is_verified,
            "online": u.id in online, "sessions": len(sess),
            "minutes": round(sum(session_minutes(s, idle_minutes=idle) for s in sess), 1),
            "first_login": _iso(min((s.login_at for s in sess), default=None)), "last_seen": _iso(last),
            "bookings": len(bookings), "confirmed": len(confirmed),
            "booked_value": round(sum(b.amount for b in confirmed), 2),
            "commission": round(sum(b.agent_commission or 0 for b in confirmed), 2),
            "actions": actions,
        })
    out.sort(key=lambda r: (not r["online"], -r["minutes"]))
    return {"since": _iso(since), "days": days, "people": out}


@admin_router.get("/team/sessions", summary="Login history", dependencies=[Depends(staff)])
def team_sessions(user_id: Optional[int] = None, days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    idle = st.get_float("idle_session_minutes") or 30
    q = db.query(LoginSession, User).join(User, User.id == LoginSession.user_id).filter(LoginSession.login_at >= _since(days))
    if user_id:
        q = q.filter(LoginSession.user_id == user_id)
    rows = q.order_by(LoginSession.login_at.desc()).limit(500).all()
    return [{**_session_out(s, idle), "name": u.full_name} for s, u in rows]


@admin_router.get("/audit", summary="Action log", dependencies=[Depends(staff)])
def audit_log(user_id: Optional[int] = None, action: Optional[str] = None, days: int = Query(7, ge=1, le=90),
              db: Session = Depends(get_db)):
    q = db.query(AuditLog).filter(AuditLog.created_at >= _since(days))
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    if action:
        q = q.filter(AuditLog.action.like(f"{action}%"))
    return [{"id": a.id, "user_id": a.user_id, "user_name": a.user_name, "role": a.role, "action": a.action,
             "target": a.target, "details": a.details, "created_at": _iso(a.created_at)}
            for a in q.order_by(AuditLog.created_at.desc()).limit(500).all()]


# ------------------------------------------------------------------ agents (admin)

class AgentUpdate(BaseModel):
    is_verified: Optional[bool] = None
    is_active: Optional[bool] = None
    commission_percent: Optional[float] = Field(None, ge=0, le=50)
    clear_commission: bool = False


def _agent_row(db: Session, u: User, online: set) -> dict:
    bookings = db.query(SupplierBooking).filter(SupplierBooking.customer_id == u.id).all()
    confirmed = [b for b in bookings if b.status == SupplierBookingStatus.CONFIRMED]
    last = db.query(func.max(LoginSession.last_seen_at)).filter(LoginSession.user_id == u.id).scalar()
    return {
        "id": u.id, "name": u.full_name, "company": u.company_name, "email": u.email, "phone": u.phone,
        "gstin": u.gstin, "is_verified": u.is_verified, "is_active": u.is_active, "online": u.id in online,
        "joined": _iso(u.created_at), "last_seen": _iso(last),
        "commission_percent": u.agent_commission_percent,
        "effective_commission_percent": u.agent_commission_percent if u.agent_commission_percent is not None else st.get_float("agent_commission_percent"),
        "bookings": len(bookings), "confirmed": len(confirmed),
        "booked_value": round(sum(b.amount for b in confirmed), 2),
        "commission_earned": round(sum(b.agent_commission or 0 for b in confirmed), 2),
    }


@admin_router.get("/agents", summary="All agents with business stats", dependencies=[Depends(staff)])
def list_agents(db: Session = Depends(get_db)):
    online = _online_ids(db)
    rows = [_agent_row(db, u, online) for u in db.query(User).filter(User.role == UserRole.AGENT).order_by(User.created_at.desc()).all()]
    return {"default_commission_percent": st.get_float("agent_commission_percent"), "agents": rows}


@admin_router.get("/agents/{agent_id}", summary="One agent — bookings & login history", dependencies=[Depends(staff)])
def agent_detail(agent_id: int, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == agent_id, User.role == UserRole.AGENT).first()
    if not u:
        raise HTTPException(status_code=404, detail="Agent not found.")
    idle = st.get_float("idle_session_minutes") or 30
    bookings = db.query(SupplierBooking).filter(SupplierBooking.customer_id == u.id).order_by(SupplierBooking.created_at.desc()).limit(200).all()
    sessions = db.query(LoginSession).filter(LoginSession.user_id == u.id).order_by(LoginSession.login_at.desc()).limit(50).all()
    return {
        "agent": _agent_row(db, u, _online_ids(db)),
        "bookings": [{"id": b.id, "product": b.product, "title": b.title, "status": b.status.value, "amount": b.amount,
                      "commission": b.agent_commission, "customer": b.contact_name, "phone": b.contact_phone,
                      "travel_date": b.travel_date, "created_at": _iso(b.created_at), "reference": b.pnr or b.confirmation_no}
                     for b in bookings],
        "sessions": [_session_out(s, idle) for s in sessions],
    }


@admin_router.put("/agents/{agent_id}", summary="Approve / suspend / set commission", dependencies=[Depends(staff)])
def update_agent(agent_id: int, payload: AgentUpdate, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    u = db.query(User).filter(User.id == agent_id, User.role == UserRole.AGENT).first()
    if not u:
        raise HTTPException(status_code=404, detail="Agent not found.")
    changes = []
    if payload.is_verified is not None and payload.is_verified != u.is_verified:
        u.is_verified = payload.is_verified
        changes.append("approved" if payload.is_verified else "unapproved")
        db.add(Notification(user_id=u.id, title="Agent account approved" if payload.is_verified else "Agent approval withdrawn",
                            message="You can now book for your customers." if payload.is_verified else "Please contact support."))
    if payload.is_active is not None and payload.is_active != u.is_active:
        u.is_active = payload.is_active
        changes.append("reactivated" if payload.is_active else "suspended")
    if payload.clear_commission:
        u.agent_commission_percent = None
        changes.append("commission → default")
    elif payload.commission_percent is not None and payload.commission_percent != u.agent_commission_percent:
        u.agent_commission_percent = payload.commission_percent
        changes.append(f"commission → {payload.commission_percent}%")
    db.commit()
    if changes:
        audit(db, me, "agent." + changes[0].split(" ")[0], f"Agent #{u.id} {u.company_name or u.full_name}", ", ".join(changes))
    return _agent_row(db, u, _online_ids(db))


# ------------------------------------------------------------------ settings

class SettingsUpdate(BaseModel):
    values: Dict[str, str]


@public_router.get("/public", summary="Public company info")
def public_settings():
    return {k: st.get(k) for k in ("company_name", "support_email", "support_phone", "company_address", "gst_number")}


@admin_router.get("/settings", summary="All platform settings", dependencies=[Depends(staff)])
def get_settings():
    vals = st.all_values()
    return [{"key": k, "label": lab, "type": typ, "group": grp, "value": vals[k]} for k, (lab, typ, _d, grp) in st.SCHEMA.items()]


@admin_router.put("/settings", summary="Update settings (Super Admin)", dependencies=[Depends(super_only)])
def put_settings(payload: SettingsUpdate, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    changed = []
    for k, v in payload.values.items():
        if k not in st.SCHEMA:
            raise HTTPException(status_code=422, detail=f"Unknown setting: {k}")
        v = str(v).strip()
        typ = st.SCHEMA[k][1]
        if typ == "number" and v:
            try:
                n = float(v)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"{st.SCHEMA[k][0]} must be a number.")
            if n < 0 or n > 100000:
                raise HTTPException(status_code=422, detail=f"{st.SCHEMA[k][0]} is out of range.")
        if typ == "bool":
            v = "true" if v.lower() in ("1", "true", "yes", "on") else "false"
        row = db.query(AppSetting).filter(AppSetting.key == k).first()
        old = row.value if row else None
        if old == v:
            continue
        if row:
            row.value, row.updated_by = v, me.id
        else:
            db.add(AppSetting(key=k, value=v, updated_by=me.id))
        changed.append(f"{st.SCHEMA[k][0]}: {old if old is not None else st.get(k)} → {v}")
    db.commit()
    st.refresh()
    if changed:
        audit(db, me, "settings.updated", "Settings", "; ".join(changed))
    return get_settings()
