"""
Last-resort password reset: writes directly to the database file, bypassing the API
entirely. Use this ONLY when nobody can log in as an admin at all (e.g. the sole
admin forgot their password) -- otherwise use:
  - POST /auth/users/{username}/reset-password (admin resets someone else), or
  - the /auth/forgot-password + /auth/reset-password token flow (self-service)

This script requires filesystem access to the server's database, which is exactly
the trust boundary that makes it safe: anyone who can run this already has direct
access to the machine running the platform.

Usage:
    python3 scripts/reset_password.py --username admin --password <new password>
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal, Base, engine
from app import models
from app.auth.security import hash_password


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True, help="New password (min 8 characters)")
    args = p.parse_args()

    if len(args.password) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)

    Base.metadata.create_all(bind=engine)  # no-op if tables already exist
    db = SessionLocal()
    try:
        user = db.query(models.UserORM).filter_by(username=args.username).first()
        if not user:
            print(f"No user '{args.username}' found in the database.")
            sys.exit(1)

        new_hash, new_salt = hash_password(args.password)
        user.password_hash = new_hash
        user.password_salt = new_salt
        db.commit()
        print(f"Password for '{args.username}' has been reset directly in the database.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
