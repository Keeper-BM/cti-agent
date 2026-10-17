"""Validate effective settings without echoing secret values or URLs."""

import sys

from pydantic import ValidationError
from sqlalchemy.engine import make_url

from backend.core.config import get_settings


def main() -> int:
    try:
        settings = get_settings()
        url = make_url(settings.database_url)
        if url.drivername not in {"sqlite", "postgresql+psycopg"}:
            print("Configuration error: DATABASE_URL must use sqlite or postgresql+psycopg.")
            return 1
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, item["loc"])) for item in exc.errors())
        print(f"Configuration error: check these settings: {fields}.", file=sys.stderr)
        return 1
    except Exception:
        print("Configuration error: check APP_ENV and DATABASE_URL.", file=sys.stderr)
        return 1
    print("Effective API/Worker settings validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
