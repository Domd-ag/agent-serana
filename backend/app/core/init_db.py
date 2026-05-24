import asyncio
from sqlalchemy import text
from .database import engine, Base
from .models import User
from sqlalchemy.ext.asyncio import AsyncSession
from .logger import get_logger

logger = get_logger(__name__)


async def init_db():
    logger.info("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await migrate_profile_facts_table(conn)
        await migrate_messages_table(conn)
        await migrate_goals_table(conn)
        await ensure_working_memories_table(conn)
    logger.info("Database tables created successfully!")


async def migrate_profile_facts_table(conn):
    result = await conn.execute(text("PRAGMA table_info(profile_facts)"))
    existing_columns = {row[1] for row in result.fetchall()}

    column_statements = {
        "category": "ALTER TABLE profile_facts ADD COLUMN category VARCHAR",
        "confidence": "ALTER TABLE profile_facts ADD COLUMN confidence FLOAT NOT NULL DEFAULT 1.0",
        "is_active": "ALTER TABLE profile_facts ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
        "updated_at": "ALTER TABLE profile_facts ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    }

    for column_name, statement in column_statements.items():
        if column_name not in existing_columns:
            logger.info("Adding missing column '%s' to profile_facts", column_name)
            await conn.execute(text(statement))


async def migrate_goals_table(conn):
    result = await conn.execute(text("PRAGMA table_info(goals)"))
    existing_columns = {row[1] for row in result.fetchall()}

    column_statements = {
        "planning_summary": "ALTER TABLE goals ADD COLUMN planning_summary TEXT",
        "thinking_blocks": "ALTER TABLE goals ADD COLUMN thinking_blocks TEXT",
    }

    for column_name, statement in column_statements.items():
        if column_name not in existing_columns:
            logger.info("Adding missing column '%s' to goals", column_name)
            await conn.execute(text(statement))


async def migrate_messages_table(conn):
    result = await conn.execute(text("PRAGMA table_info(messages)"))
    existing_columns = {row[1] for row in result.fetchall()}

    column_statements = {
        "thinking_blocks": "ALTER TABLE messages ADD COLUMN thinking_blocks TEXT",
        "tool_calls": "ALTER TABLE messages ADD COLUMN tool_calls TEXT",
    }

    for column_name, statement in column_statements.items():
        if column_name not in existing_columns:
            logger.info("Adding missing column '%s' to messages", column_name)
            await conn.execute(text(statement))


async def ensure_working_memories_table(conn):
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='working_memories'")
    )
    table_name = result.scalar_one_or_none()
    if table_name:
        return

    logger.info("Creating missing table 'working_memories'")
    await conn.execute(
        text(
            """
            CREATE TABLE working_memories (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                scope VARCHAR NOT NULL,
                session_id VARCHAR,
                goal_id VARCHAR,
                key VARCHAR NOT NULL,
                content TEXT NOT NULL,
                source VARCHAR,
                priority FLOAT NOT NULL DEFAULT 1.0,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
    )


async def create_default_user(session: AsyncSession):
    from sqlalchemy import select
    
    result = await session.execute(select(User).where(User.name == "default"))
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(name="default")
        session.add(user)
        await session.commit()
        logger.info("Default user created!")
    else:
        logger.info("Default user already exists!")
    
    return user


async def main():
    await init_db()
    
    from .database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        await create_default_user(session)


if __name__ == "__main__":
    asyncio.run(main())
