"""Read-only diagnosis of live skill-catalog tenant constraints."""

import sys
from pathlib import Path

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine


with engine.connect() as connection:
    inspector = inspect(connection)
    print({
        "constraints": inspector.get_unique_constraints("global_skills"),
        "indexes": inspector.get_indexes("global_skills"),
        "rows_by_org": connection.execute(text(
            "SELECT organization_id, count(*) FROM global_skills "
            "GROUP BY organization_id ORDER BY organization_id"
        )).all(),
        "cross_org_names": connection.execute(text(
            "SELECT lower(name), count(DISTINCT organization_id) FROM global_skills "
            "GROUP BY lower(name) HAVING count(DISTINCT organization_id) > 1 "
            "ORDER BY 2 DESC LIMIT 20"
        )).all(),
    })
