"""Initial Phase 4 schema baseline (autogenerate-friendly placeholder).

Runtime schema for local/tests is applied by `init_db()` (create_all + migrations).
Use `alembic revision --autogenerate` against a clean DB to refresh this for Postgres deploys.
"""

revision = "p4_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Prefer app init_db for expand/migrate on existing deployments.
    pass


def downgrade() -> None:
    pass
