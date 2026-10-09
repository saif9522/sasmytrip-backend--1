import secrets
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models.models import User, UserRole, OtpCode
from app.schemas.schemas import (
    RegisterRequest, LoginRequest, TokenResponse, UserOut,
    ForgotPasswordRequest, ForgotPasswordResponse, ResetPasswordRequest,
    SendOtpRequest, SendOtpResponse, VerifyOtpRequest,
)
from app.core.security import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["Auth"])


# ----------------------------------------------------
# Auto-seed Super Admin on Startup (from .env)
# ----------------------------------------------------
# SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD / SUPER_ADMIN_NAME / SUPER_ADMIN_PHONE in .env.
# - Account missing  -> it is created.
# - Account exists   -> role is kept as super_admin; the password is changed ONLY
#                       when SUPER_ADMIN_RESET_PASSWORD=true (so a password changed
#                       later is not silently overwritten on every restart).
def seed_super_admin():
    import os
    email = os.getenv("SUPER_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("SUPER_ADMIN_PASSWORD", "")
    if not email or not password:
        return  # nothing configured — use seed_super_admin.py instead
    if len(password) < 6:
        print(">>> SUPER_ADMIN_PASSWORD must be at least 6 characters — super admin not seeded <<<")
        return
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == email).first()
        if not admin:
            db.add(User(
                full_name=os.getenv("SUPER_ADMIN_NAME", "Super Admin").strip() or "Super Admin",
                email=email,
                phone=os.getenv("SUPER_ADMIN_PHONE", "").strip() or None,
                password_hash=hash_password(password),
                role=UserRole.SUPER_ADMIN,
                is_verified=True,
                is_active=True,
            ))
            db.commit()
            print(f">>> Super Admin created: {email} <<<")
        else:
            admin.role = UserRole.SUPER_ADMIN
            admin.is_active = True
            admin.is_verified = True
            if os.getenv("SUPER_ADMIN_RESET_PASSWORD", "").strip().lower() in ("1", "true", "yes"):
                admin.password_hash = hash_password(password)
                print(f">>> Super Admin password reset from .env: {email} <<<")
            db.commit()
    except Exception as e:
        print(f"Error seeding super admin: {e}")
    finally:
        db.close()


# Called from app.main AFTER the database tables are created.


# ----------------------------------------------------
# Auth Endpoints
# ----------------------------------------------------
@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
    description=(
        "Creates a new account as **Customer**, **Agent**, **Distributor**, **Admin**, or **Super Admin**."
    ),
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    user = User(
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role=payload.role,
        company_name=payload.company_name,
        gstin=payload.gstin,
        is_verified=(payload.role in (UserRole.CUSTOMER, UserRole.ADMIN, UserRole.SUPER_ADMIN)),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in to a specific role portal",
    description=(
        "Logs a user in. The `role` field must match the role the account was "
        "registered with."
    ),
)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    # A Super Admin may sign in from either staff option on the admin login page.
    staff_ok = user.role == UserRole.SUPER_ADMIN and payload.role == UserRole.ADMIN
    if user.role != payload.role and not staff_ok:
        raise HTTPException(
            status_code=403,
            detail=f"This email is registered as '{user.role.value}', not '{payload.role.value}'. "
                   f"Please choose the correct portal.",
        )

    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated.")

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get(
    "/me",
    response_model=UserOut,
    summary="Get the currently logged-in user's profile",
)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    summary="Request a password reset link",
)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    generic_message = "If an account with that email exists, a reset link has been sent."

    if not user:
        return ForgotPasswordResponse(message=generic_message)

    token = secrets.token_urlsafe(32)
    user.reset_token = token
    user.reset_token_expires = datetime.utcnow() + timedelta(minutes=30)
    db.commit()

    return ForgotPasswordResponse(message=generic_message, dev_reset_token=token)


@router.post(
    "/reset-password",
    summary="Reset password using a token from /forgot-password",
)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_token == payload.token).first()
    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")

    user.password_hash = hash_password(payload.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    db.commit()

    return {"message": "Password updated. You can now log in with your new password."}


@router.post(
    "/send-otp",
    response_model=SendOtpResponse,
    summary="Send a login OTP to a registered phone number",
)
def send_otp(payload: SendOtpRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.phone == payload.phone, User.role == payload.role).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="No account found with this phone number for the selected account type.",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated.")

    code = f"{random.randint(0, 999999):06d}"
    otp = OtpCode(
        phone=payload.phone,
        role=payload.role,
        code=code,
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    )
    db.add(otp)
    db.commit()

    return SendOtpResponse(message="A 6-digit code has been sent to your phone.", dev_otp=code)


@router.post(
    "/verify-otp",
    response_model=TokenResponse,
    summary="Verify a login OTP and log in",
)
def verify_otp(payload: VerifyOtpRequest, db: Session = Depends(get_db)):
    otp = (
        db.query(OtpCode)
        .filter(
            OtpCode.phone == payload.phone,
            OtpCode.role == payload.role,
            OtpCode.code == payload.otp,
            OtpCode.is_used == False,  # noqa: E712
        )
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if not otp or otp.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This code is invalid or has expired.")

    user = db.query(User).filter(User.phone == payload.phone, User.role == payload.role).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="Account not found or deactivated.")

    otp.is_used = True
    db.commit()

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))
