import peewee as pw
import pytest

import peewee_gis as pg

COMPILER = pw.PostgresqlDatabase(None)


def sql(node: pw.Node) -> tuple[str, list[object]]:
    """Render a node/query for PostgreSQL, without a connection."""
    return COMPILER.get_sql_context().sql(node).query()


@pytest.fixture(scope="module")
def setup_database(setup_database):
    """PostGIS must exist before `setup_schema` creates the tables (outside the test transactions)."""
    if isinstance(setup_database, pw.PostgresqlDatabase):
        setup_database.execute(pg.extension("postgis"))
    yield setup_database
