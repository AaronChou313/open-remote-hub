"""Operator command for one-use Cloud invitations."""

import argparse
import secrets
import time
from cloud.store import database, digest, initialize


def create(days=7):
    code = secrets.token_urlsafe(24)
    initialize()
    with database() as db:
        db.execute(
            "INSERT INTO invitations(digest,expires,used) VALUES (?,?,0)",
            (digest(code), time.time() + days * 86400),
        )
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    print(create(args.days))
