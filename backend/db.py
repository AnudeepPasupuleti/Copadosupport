from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, text
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


class TeamTask(Base):
    __tablename__ = "team_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="new")
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    due_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    tags: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
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


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("team_tasks.id"), nullable=True)
    read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class OrgTeam(Base):
    __tablename__ = "org_teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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


engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=not config.DATABASE_URL.startswith("sqlite"),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_schema()


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
            if engine.dialect.name == "sqlite":
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'member'")
                )
            else:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN role VARCHAR(32) "
                        "NOT NULL DEFAULT 'member'"
                    )
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

        # Bootstrap Super Admin from seeded password Admin when none exist yet
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
