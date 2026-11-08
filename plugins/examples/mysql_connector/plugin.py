"""示例插件：MySQL 数据源（基于 SQLAlchemy，凭据由宿主 DPAPI 加密后注入）。"""
from urllib.parse import quote_plus

from aixian.plugin_sdk import DataSourcePlugin, QueryResult, TableSchema


class MySQLDataSource(DataSourcePlugin):
    def _engine(self, config):
        from sqlalchemy import create_engine

        url = "mysql+pymysql://{}:{}@{}:{}/{}".format(
            quote_plus(str(config.get("user", ""))), quote_plus(str(config.get("password", ""))),
            config.get("host", "127.0.0.1"), config.get("port", 3306), config.get("database", ""))
        return create_engine(url, pool_pre_ping=True)

    def test_connection(self, config: dict) -> bool:
        from sqlalchemy import text

        engine = self._engine(config)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        finally:
            engine.dispose()

    def list_schema(self, config: dict) -> list[TableSchema]:
        from sqlalchemy import inspect

        engine = self._engine(config)
        try:
            inspector = inspect(engine)
            return [TableSchema(name=name, columns=[{"name": c["name"], "type": str(c["type"])} for c in inspector.get_columns(name)])
                    for name in inspector.get_table_names()]
        finally:
            engine.dispose()

    def query(self, config: dict, sql: str) -> QueryResult:
        from sqlalchemy import text

        engine = self._engine(config)
        try:
            with engine.connect() as conn:
                cursor = conn.execute(text(sql))
                columns = list(cursor.keys())
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return QueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=False)
        finally:
            engine.dispose()
