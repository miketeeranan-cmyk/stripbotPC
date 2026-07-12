"""
Master-password-gated admin tool for the dashboard's login gate.

The dashboard verifies each login against a one-way password *hash* (which
nobody, not even the master, can read back). To let the master still VIEW the
real passwords, this tool stores a second, master-encrypted copy of each
password alongside the hash, in a local SQLite database:

    users.db
    master(id=1, salt, check_token)
    users(username, hash, enc)

    hash : generate_password_hash(pw)     -> dashboard login (no master needed)
    enc  : Fernet(key).encrypt(pw)        -> master-only viewing

The Fernet key is derived from the master password + a random salt via PBKDF2,
so a stolen (gitignored, local) users.db still can't reveal any password
without the master password.

Run:
    python setup_users.py

- First run (no users.db): set a master password, then create 3 users.
- Later runs: enter the master password to unlock, then view all passwords,
  reset one user, or change the master password.

Nothing plaintext is ever written to disk, and only the unlocked "view all"
action ever prints a real password.
"""

import base64
import getpass
import json
import os
import sqlite3
import time

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "users.db")
# Only consulted once, to migrate a pre-database setup forward.
OLD_JSON_FILE = os.path.join(BASE_DIR, "users.json")
NUM_USERS = 3
KDF_ITERATIONS = 390000
# A fixed token we encrypt with the derived key so a later run can verify the
# master password by trying to decrypt it (wrong password -> InvalidToken).
CHECK_TOKEN = b"stripchat-tracker-master-check"


# ------------------------------ crypto ------------------------------
def _derive_key(master: str, salt: bytes) -> bytes:
    """Derive a urlsafe-base64 Fernet key from the master password + salt."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(master.encode()))


def _record_for(fernet: Fernet, password: str) -> dict:
    """The stored pair for one user: login hash + master-viewable ciphertext."""
    return {
        "hash": generate_password_hash(password),
        "enc": fernet.encrypt(password.encode()).decode(),
    }


# ------------------------------ prompts ------------------------------
def _prompt_password(label: str) -> str:
    """Prompt (hidden) for a non-empty password, confirmed twice."""
    while True:
        password = getpass.getpass(f"{label}: ")
        if not password:
            print("Password can't be empty. Try again.")
            continue
        if getpass.getpass(f"Confirm {label.lower()}: ") != password:
            print("Passwords didn't match. Try again.")
            continue
        return password


def _prompt_username(index: int, taken: set) -> str:
    while True:
        username = input(f"User {index} -- username: ").strip()
        if not username:
            print("Username can't be empty. Try again.")
            continue
        if username in taken:
            print(f'"{username}" was already used above. Pick a different username.')
            continue
        return username


# ------------------------------ storage ------------------------------
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS master (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            salt TEXT NOT NULL,
            check_token TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            hash TEXT NOT NULL,
            enc TEXT NOT NULL
        )
    """)
    return conn


def _save(data: dict) -> None:
    conn = _connect()
    conn.execute("DELETE FROM master")
    conn.execute("DELETE FROM users")
    conn.execute(
        "INSERT INTO master (id, salt, check_token) VALUES (1, ?, ?)",
        (data["master"]["salt"], data["master"]["check"]),
    )
    conn.executemany(
        "INSERT INTO users (username, hash, enc) VALUES (?, ?, ?)",
        [(name, rec["hash"], rec["enc"]) for name, rec in data["users"].items()],
    )
    conn.commit()
    conn.close()


def _migrate_from_json_if_present() -> None:
    """One-time upgrade path from the old users.json storage. If it's the
    new-style JSON (master + users, i.e. already had a master password),
    import it losslessly into users.db. If it's the older hash-only format
    that predates the master password, there's nothing to carry over --
    rename it out of the way so it isn't re-checked (and re-flagged) on
    every future run."""
    if not os.path.isfile(OLD_JSON_FILE):
        return
    try:
        with open(OLD_JSON_FILE) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = None

    if isinstance(data, dict) and "master" in data and "users" in data:
        _save(data)
        os.rename(OLD_JSON_FILE, OLD_JSON_FILE + ".migrated")
        print(
            f"Migrated {os.path.basename(OLD_JSON_FILE)} into "
            f"{os.path.basename(DB_FILE)} (old file kept as "
            f"users.json.migrated, safe to delete).\n"
        )
    else:
        os.rename(OLD_JSON_FILE, OLD_JSON_FILE + ".old-format")
        print(
            f"{os.path.basename(OLD_JSON_FILE)} was in the old pre-database "
            f"format and couldn't be migrated automatically (renamed to "
            f"users.json.old-format). Set up fresh below.\n"
        )


def _load_valid() -> dict | None:
    """Return the current data as {"master": {...}, "users": {...}}, or None
    if users.db doesn't exist yet or has no master password set."""
    if not os.path.isfile(DB_FILE):
        return None
    conn = _connect()
    row = conn.execute("SELECT salt, check_token FROM master WHERE id = 1").fetchone()
    if row is None:
        conn.close()
        return None
    users = {
        username: {"hash": hash_, "enc": enc}
        for username, hash_, enc in conn.execute("SELECT username, hash, enc FROM users")
    }
    conn.close()
    return {"master": {"salt": row[0], "check": row[1]}, "users": users}


# ------------------------------ flows ------------------------------
def first_time_setup() -> None:
    print("First-time setup for the Stripchat Tracker dashboard.\n")
    print("Set a MASTER password. It unlocks this admin tool and lets you view")
    print("or reset the login passwords later. There is no recovery if you")
    print("forget it -- you'd have to delete users.db and start over.\n")
    master = _prompt_password("Master password")
    salt = os.urandom(16)
    fernet = Fernet(_derive_key(master, salt))

    print(f"\nNow create {NUM_USERS} dashboard logins.\n")
    users = {}
    taken = set()
    for i in range(1, NUM_USERS + 1):
        username = _prompt_username(i, taken)
        taken.add(username)
        password = _prompt_password(f'Password for "{username}"')
        users[username] = _record_for(fernet, password)
        print()

    _save({
        "master": {
            "salt": salt.hex(),
            "check": fernet.encrypt(CHECK_TOKEN).decode(),
        },
        "users": users,
    })
    print(f"Wrote {DB_FILE} with {len(users)} user(s): {', '.join(users)}")
    print("Passwords are stored only as a hash + a master-encrypted copy -- "
          "nothing plaintext was written.")


def _unlock(data: dict) -> Fernet | None:
    """Prompt for the master password until it verifies, or the user quits.
    Returns a ready Fernet on success, None if the user gives up."""
    salt = bytes.fromhex(data["master"]["salt"])
    check = data["master"]["check"].encode()
    while True:
        master = getpass.getpass("Master password (blank to quit): ")
        if not master:
            return None
        fernet = Fernet(_derive_key(master, salt))
        try:
            fernet.decrypt(check)
        except InvalidToken:
            time.sleep(0.5)  # slow down guessing
            print("Wrong master password.\n")
            continue
        return fernet


def _view_all(data: dict, fernet: Fernet) -> None:
    print("\nCurrent passwords:")
    for username, rec in data["users"].items():
        password = fernet.decrypt(rec["enc"].encode()).decode()
        print(f"  {username} : {password}")
    print()


def _reset_one(data: dict, fernet: Fernet) -> None:
    usernames = list(data["users"])
    print("\nWhich user's password do you want to reset?")
    for i, name in enumerate(usernames, 1):
        print(f"  {i}) {name}")
    choice = input("Number: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(usernames)):
        print("Not a valid choice.\n")
        return
    username = usernames[int(choice) - 1]
    password = _prompt_password(f'New password for "{username}"')
    data["users"][username] = _record_for(fernet, password)
    _save(data)
    print(f'Updated "{username}". The other users were left unchanged.\n')


def admin_menu(data: dict, fernet: Fernet) -> None:
    print("\nUnlocked. What would you like to do?\n")
    while True:
        print("  1) View all passwords")
        print("  2) Reset one user's password")
        print("  3) Change the master password")
        print("  4) Quit")
        choice = input("Choose: ").strip()
        if choice == "1":
            _view_all(data, fernet)
        elif choice == "2":
            _reset_one(data, fernet)
        elif choice == "3":
            fernet = _rekey_master(data, fernet)
        elif choice == "4":
            print("Bye.")
            return
        else:
            print("Please enter 1, 2, 3, or 4.\n")


def _rekey_master(data: dict, old_fernet: Fernet) -> Fernet:
    """Change the master password, re-encrypting every viewable copy under the
    new key. Returns the new Fernet so the session stays unlocked."""
    print("\nSet a NEW master password. Every stored password will be "
          "re-encrypted under it.")
    master = _prompt_password("New master password")
    salt = os.urandom(16)
    new_fernet = Fernet(_derive_key(master, salt))
    for rec in data["users"].values():
        plaintext = old_fernet.decrypt(rec["enc"].encode())
        rec["enc"] = new_fernet.encrypt(plaintext).decode()
    data["master"] = {
        "salt": salt.hex(),
        "check": new_fernet.encrypt(CHECK_TOKEN).decode(),
    }
    _save(data)
    print("Master password changed.\n")
    return new_fernet


def main() -> None:
    _migrate_from_json_if_present()
    data = _load_valid()
    if data is None:
        first_time_setup()
        return
    fernet = _unlock(data)
    if fernet is None:
        print("No master password entered -- nothing changed.")
        return
    admin_menu(data, fernet)


if __name__ == "__main__":
    main()
