#!/usr/bin/env python3
from __future__ import annotations

from _common import connect_db, init_db, rebuild_fts


def main() -> None:
    conn = connect_db()
    init_db(conn)
    rebuild_fts(conn)
    conn.close()
    print("Indexes refreshed.")


if __name__ == "__main__":
    main()
