"""Create the first local administrator without passwords in command arguments or logs."""

import argparse
import getpass
import re
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.auth.passwords import hash_password
from backend.core.audit import audit
from backend.core.database import get_engine
from backend.models.tables import LoginSession, User


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--display-name", default="관리자")
    parser.add_argument("--password-file", type=Path)
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Recover an existing account using local DB administrator access",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", args.username):
        parser.error("Use a lowercase username of 3 to 64 characters")
    if not args.display_name.strip() or len(args.display_name) > 100:
        parser.error("Display name must contain 1 to 100 characters")
    password = (
        args.password_file.read_text(encoding="utf-8").rstrip("\r\n")
        if args.password_file
        else getpass.getpass("New administrator password: ")
    )
    try:
        hashed = hash_password(password)
    except ValueError:
        parser.error("Password must contain 12 to 256 characters")
    with Session(get_engine()) as db, db.begin():
        if args.reset_password:
            user = db.scalar(select(User).where(User.username == args.username))
            if not user:
                parser.error("Account not found")
            user.password_hash = hashed
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            audit(db, "password.recovered", target_id=user.id)
            print("Password changed; existing sessions revoked. Role and active state preserved.")
            return
        if db.scalar(select(User.id).where(User.role == "ADMIN", User.is_active.is_(True))):
            parser.error(
                "An active administrator already exists; use the account management screen"
            )
        if db.scalar(select(User.id).where(User.username == args.username)):
            parser.error("This username already exists")
        user = User(
            username=args.username,
            display_name=args.display_name.strip(),
            password_hash=hashed,
            role="ADMIN",
        )
        db.add(user)
        db.flush()
        audit(db, "user.bootstrap", actor_id=user.id, target_id=user.id)
    print("Administrator created. Set AUTH_MODE=accounts and restart API and worker.")


if __name__ == "__main__":
    main()
