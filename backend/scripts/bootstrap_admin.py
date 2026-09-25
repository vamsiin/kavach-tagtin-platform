"""
One-time convenience: create the first admin user against a running instance of the
API. /auth/register only accepts the very first user on a fresh database (see
routers/auth.py) -- after that it 403s and you must use POST /auth/users as an admin.

Usage:
    python3 scripts/bootstrap_admin.py --url http://localhost:8000 \
        --username admin --full-name "Platform Admin" --password <password>
"""
import argparse
import json
import urllib.request
import urllib.error


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--username", required=True)
    p.add_argument("--full-name", required=True)
    p.add_argument("--password", required=True)
    args = p.parse_args()

    payload = json.dumps({
        "username": args.username,
        "full_name": args.full_name,
        "role": "admin",
        "password": args.password,
    }).encode()

    req = urllib.request.Request(
        f"{args.url}/auth/register", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print("Admin created:", json.loads(resp.read()))
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Failed ({e.code}): {body}")
        if e.code == 403:
            print("Registration is closed -- an admin already exists. Log in and "
                  "use POST /auth/users instead.")


if __name__ == "__main__":
    main()
