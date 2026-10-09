"""
Create (or promote) a Super Admin account.

Admin/Super Admin accounts cannot be created through the public /api/auth/register
endpoint (by design). Use this script on the server.

Usage (Git Bash / CMD / PowerShell / Linux), run from the backend folder:

    python seed_super_admin.py --email you@example.com --password "StrongPass@123" --name "Your Name"

Run without arguments to be asked interactively.
If the email already exists, the account is promoted to Super Admin and its
password is replaced with the one you give.

After that, log in at /admin/login. The Super Admin can create more Admins from
the Admin Dashboard -> Admins.
"""
import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from app.database import SessionLocal, Base, engine  # noqa: E402
from app.models.models import User, UserRole  # noqa: E402
from app.core.security import hash_password  # noqa: E402

Base.metadata.create_all(bind=engine)


def ask(prompt, secret=False):
    if secret:
        try:
            import getpass
            return getpass.getpass(prompt)
        except Exception:
            pass
    return input(prompt)


def main():
    ap = argparse.ArgumentParser(description="Create or promote a Super Admin")
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--name", default=None)
    ap.add_argument("--phone", default=None)
    args = ap.parse_args()

    email = (args.email or ask("Super Admin email: ")).strip().lower()
    if "@" not in email:
        print("Enter a valid email. Aborting.")
        sys.exit(1)
    password = args.password or ask("Password (min 6 chars): ", secret=True)
    if len(password) < 6:
        print("Password must be at least 6 characters. Aborting.")
        sys.exit(1)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.role = UserRole.SUPER_ADMIN
            user.is_active = True
            user.is_verified = True
            user.password_hash = hash_password(password)
            if args.name:
                user.full_name = args.name
            if args.phone:
                user.phone = args.phone
            db.commit()
            print(f"\nExisting account '{email}' is now a Super Admin (password updated).")
        else:
            name = args.name or (ask("Full name: ").strip() if not args.email else "") or "Super Admin"
            db.add(User(
                full_name=name, email=email, phone=args.phone,
                password_hash=hash_password(password),
                role=UserRole.SUPER_ADMIN, is_verified=True, is_active=True,
            ))
            db.commit()
            print(f"\nSuper Admin '{email}' created.")
        print("Log in at http://localhost:5173/admin/login")
    finally:
        db.close()


if __name__ == "__main__":
    main()
