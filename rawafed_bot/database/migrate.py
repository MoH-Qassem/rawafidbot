"""Lightweight SQLite schema patches for additive columns/tables."""
from sqlalchemy import inspect, text

from rawafed_bot.database.connection import engine, Base


def _add_column_if_missing(table: str, column: str, ddl: str) -> None:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column not in cols:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def ensure_schema_patches() -> None:
    """Add missing columns/tables without wiping data."""
    # Create any new tables (roles, permissions, company_groups, …)
    import rawafed_bot.database.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    _add_column_if_missing(
        "journal_entries", "idempotency_key", "idempotency_key VARCHAR(32)"
    )
    insp = inspect(engine)
    if "journal_entries" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("journal_entries")}
        if "idempotency_key" in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_journal_entries_idempotency_key ON journal_entries (idempotency_key)"
                ))

    _add_column_if_missing("transactions", "debt_id", "debt_id INTEGER")
    _add_column_if_missing(
        "transactions", "idempotency_key", "idempotency_key VARCHAR(32)"
    )
    insp = inspect(engine)
    if "transactions" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("transactions")}
        if "idempotency_key" in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_transactions_idempotency_key ON transactions (idempotency_key)"
                ))
    _add_column_if_missing("roles", "is_unique", "is_unique BOOLEAN DEFAULT 1")
    _add_column_if_missing(
        "company_groups", "notify_detail_level", "notify_detail_level VARCHAR(20) DEFAULT 'detailed'"
    )
    _add_column_if_missing("members", "telegram_username", "telegram_username VARCHAR(100)")
    _add_column_if_missing("members", "telegram_full_name", "telegram_full_name VARCHAR(200)")
    _add_column_if_missing("members", "profile_completed", "profile_completed BOOLEAN DEFAULT 0")
    _add_column_if_missing("members", "registered_via_group_id", "registered_via_group_id INTEGER")
    _add_column_if_missing("members", "deactivated_at", "deactivated_at DATETIME")
    _add_column_if_missing("members", "deactivated_by", "deactivated_by INTEGER")
    _add_column_if_missing("members", "deactivation_reason", "deactivation_reason VARCHAR(255)")
