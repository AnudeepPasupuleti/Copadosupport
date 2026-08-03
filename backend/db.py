from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[Optional[str]] = mapped_column(String(120), unique=True, nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    google_sub: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    github_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    picture: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    reports_to_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    state: Mapped["UserState"] = relationship(back_populates="user", uselist=False)
    manager: Mapped[Optional["User"]] = relationship(
        "User",
        remote_side="User.id",
        foreign_keys=[reports_to_id],
    )


class UserState(Base):
    __tablename__ = "user_state"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship(back_populates="state")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WorkspaceCaseCounter(Base):
    __tablename__ = "workspace_case_counters"

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    next_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1001)


class TeamTask(Base):
    __tablename__ = "team_tasks"
    __table_args__ = (
        Index("ix_team_tasks_ws_updated", "workspace_id", "updated_at"),
        Index("ix_team_tasks_ws_assignee_status", "workspace_id", "assignee_id", "status"),
        Index("ix_team_tasks_ws_due_at", "workspace_id", "due_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("org_teams.id"), nullable=True)
    case_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="new")
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    due_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    comments: Mapped[list["TaskComment"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("team_tasks.id"), nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    task: Mapped["TeamTask"] = relationship(back_populates="comments")
    mentions: Mapped[list["CommentMention"]] = relationship(
        back_populates="comment",
        cascade="all, delete-orphan",
    )


class CommentMention(Base):
    __tablename__ = "comment_mentions"
    __table_args__ = (UniqueConstraint("comment_id", "user_id", name="uq_comment_mention"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("task_comments.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    comment: Mapped["TaskComment"] = relationship(back_populates="mentions")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("team_tasks.id"), nullable=True)
    activity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("case_activities.id"), nullable=True)
    read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class OrgTeam(Base):
    __tablename__ = "org_teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    members: Mapped[list["OrgTeamMember"]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
    )


class OrgTeamMember(Base):
    __tablename__ = "org_team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_org_team_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("org_teams.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    team: Mapped["OrgTeam"] = relationship(back_populates="members")


class CaseActivity(Base):
    __tablename__ = "case_activities"
    __table_args__ = (Index("ix_case_activities_ws_case_id", "workspace_id", "case_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("team_tasks.id"), nullable=False, index=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    after_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    correlation_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
            "topic",
            name="uq_outbox_aggregate_version_topic",
        ),
        Index("ix_outbox_unpublished", "published_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    topic: Mapped[str] = mapped_column(String(80), nullable=False, default="workspace")
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    aggregate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", "key", name="uq_idempotency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class LoginHistory(Base):
    __tablename__ = "login_history"
    __table_args__ = (Index("ix_login_history_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    # password, github, google, login_as, login_as_end
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=not config.DATABASE_URL.startswith("sqlite"),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    _ensure_default_workspace()


def _users_columns(conn) -> set[str]:
    if engine.dialect.name == "sqlite":
        return {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'users'"
        )
    )
    return {row[0] for row in rows}


def _table_columns(conn, table: str) -> set[str]:
    if engine.dialect.name == "sqlite":
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :table"
        ),
        {"table": table},
    )
    return {row[0] for row in rows}


def _add_column(conn, table: str, ddl: str) -> None:
    cols = _table_columns(conn, table)
    col_name = ddl.split()[0]
    if col_name not in cols and col_name.lower() not in {c.lower() for c in cols}:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def _datetime_type() -> str:
    """SQLite accepts DATETIME; Postgres needs TIMESTAMP WITH TIME ZONE."""
    if engine.dialect.name == "postgresql":
        return "TIMESTAMP WITH TIME ZONE"
    return "DATETIME"


def _migrate_schema() -> None:
    with engine.begin() as conn:
        cols = _users_columns(conn)
        if "github_id" not in cols and engine.dialect.name == "sqlite":
            conn.execute(text("ALTER TABLE users ADD COLUMN github_id VARCHAR(255)"))
            conn.execute(
                text(
                    "UPDATE users SET github_id = google_sub, google_sub = NULL "
                    "WHERE auth_type = 'github' AND google_sub IS NOT NULL AND github_id IS NULL"
                )
            )
            cols = _users_columns(conn)

        if "role" not in cols:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'member'")
            )
            conn.execute(
                text(
                    "UPDATE users SET role = 'admin' "
                    "WHERE username = :username AND auth_type = 'password'"
                ),
                {"username": config.ADMIN_USERNAME},
            )

        conn.execute(
            text("UPDATE users SET role = 'member' WHERE role IS NULL OR role = ''")
        )

        super_count = conn.execute(
            text("SELECT COUNT(*) FROM users WHERE role = 'super_admin'")
        ).scalar()
        if not super_count:
            conn.execute(
                text(
                    "UPDATE users SET role = 'super_admin' "
                    "WHERE username = :username AND auth_type = 'password'"
                ),
                {"username": config.ADMIN_USERNAME},
            )

        cols = _users_columns(conn)
        if "reports_to_id" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN reports_to_id INTEGER"))

        # Phase 4 columns on existing tables
        dt = _datetime_type()
        if "team_tasks" in _existing_tables(conn):
            _add_column(conn, "team_tasks", "workspace_id INTEGER")
            _add_column(conn, "team_tasks", "team_id INTEGER")
            _add_column(conn, "team_tasks", f"due_at {dt}")
            _add_column(conn, "team_tasks", "version INTEGER NOT NULL DEFAULT 1")
            _add_column(conn, "team_tasks", f"resolved_at {dt}")
            _add_column(conn, "team_tasks", f"closed_at {dt}")

        if "notifications" in _existing_tables(conn):
            _add_column(conn, "notifications", "workspace_id INTEGER")
            _add_column(conn, "notifications", "activity_id INTEGER")

        if "org_teams" in _existing_tables(conn):
            _add_column(conn, "org_teams", "workspace_id INTEGER")

        if "login_history" in _existing_tables(conn):
            _add_column(conn, "login_history", "actor_id INTEGER")

        if "login_history" in _existing_tables(conn):
            _add_column(conn, "login_history", "actor_id INTEGER")


def _existing_tables(conn) -> set[str]:
    if engine.dialect.name == "sqlite":
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        return {row[0] for row in rows}
    rows = conn.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    )
    return {row[0] for row in rows}


def _ensure_default_workspace() -> None:
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.slug == config.DEFAULT_WORKSPACE_SLUG).first()
        if not ws:
            ws = Workspace(
                slug=config.DEFAULT_WORKSPACE_SLUG,
                name="Copado Support",
                timezone=config.DEFAULT_WORKSPACE_TIMEZONE,
            )
            db.add(ws)
            db.flush()

        users = db.query(User).all()
        for user in users:
            exists = (
                db.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.workspace_id == ws.id,
                    WorkspaceMember.user_id == user.id,
                )
                .first()
            )
            if not exists:
                db.add(
                    WorkspaceMember(
                        workspace_id=ws.id,
                        user_id=user.id,
                        role=user.role or "member",
                        active=True,
                    )
                )

        counter = db.get(WorkspaceCaseCounter, ws.id)
        if not counter:
            # Seed from legacy app setting if present
            raw = get_setting(db, "team_case_counter", "1000")
            try:
                n = int(raw) + 1
            except ValueError:
                n = 1001
            db.add(WorkspaceCaseCounter(workspace_id=ws.id, next_number=n))

        # Backfill workspace_id on rows
        db.query(TeamTask).filter(TeamTask.workspace_id.is_(None)).update(
            {TeamTask.workspace_id: ws.id}, synchronize_session=False
        )
        db.query(Notification).filter(Notification.workspace_id.is_(None)).update(
            {Notification.workspace_id: ws.id}, synchronize_session=False
        )
        db.query(OrgTeam).filter(OrgTeam.workspace_id.is_(None)).update(
            {OrgTeam.workspace_id: ws.id}, synchronize_session=False
        )

        # Dual-write due_date -> due_at where missing
        for task in db.query(TeamTask).filter(TeamTask.due_at.is_(None), TeamTask.due_date.isnot(None)):
            try:
                # Store as noon UTC for that calendar date (display still uses due_date)
                y, m, d = [int(x) for x in task.due_date.split("-")[:3]]
                task.due_at = datetime(y, m, d, 12, 0, tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                continue

        db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_setting(db, key: str, default: str = "") -> str:
    row = db.get(AppSetting, key)
    return row.value if row else default


def set_setting(db, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
