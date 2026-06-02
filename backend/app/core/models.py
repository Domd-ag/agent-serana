from sqlalchemy import Column, String, Text, Float, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base
import uuid


def generate_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    profile_facts = relationship("ProfileFact", back_populates="user", cascade="all, delete-orphan")
    resident_memories = relationship("ResidentMemory", back_populates="user", cascade="all, delete-orphan")
    memory_artifacts = relationship("MemoryArtifact", back_populates="user", cascade="all, delete-orphan")
    working_memories = relationship("WorkingMemory", back_populates="user", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    goals = relationship("Goal", back_populates="user", cascade="all, delete-orphan")
    llm_config = relationship("UserLLMConfig", back_populates="user", uselist=False, cascade="all, delete-orphan")
    llm_mode = relationship("UserLLMMode", back_populates="user", uselist=False, cascade="all, delete-orphan")


class ProfileFact(Base):
    __tablename__ = "profile_facts"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    key = Column(String, nullable=False)
    value = Column(Text, nullable=False)
    category = Column(String, nullable=True)
    confidence = Column(Float, nullable=False, default=1.0)
    is_active = Column(Boolean, nullable=False, default=True)
    source = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="profile_facts")


class ResidentMemory(Base):
    __tablename__ = "resident_memories"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    key = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String, nullable=True)
    priority = Column(Float, nullable=False, default=1.0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="resident_memories")


class MemoryArtifact(Base):
    __tablename__ = "memory_artifacts"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    session_id = Column(String, nullable=True)
    kind = Column(String, nullable=False)
    title = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    artifact_metadata = Column(Text, nullable=True)
    confidence = Column(Float, nullable=False, default=0.8)
    source = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="memory_artifacts")


class WorkingMemory(Base):
    __tablename__ = "working_memories"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    scope = Column(String, nullable=False)
    session_id = Column(String, nullable=True)
    goal_id = Column(String, nullable=True)
    key = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String, nullable=True)
    priority = Column(Float, nullable=False, default=1.0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="working_memories")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    agent_sessions = relationship("AgentSession", back_populates="chat_session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    thinking_blocks = Column(Text, nullable=True)
    tool_calls = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")
    audit_records = relationship("AuditRecord", back_populates="message", cascade="all, delete-orphan")


class Goal(Base):
    __tablename__ = "goals"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="pending")
    progress = Column(Float, default=0.0)
    planning_summary = Column(Text, nullable=True)
    thinking_blocks = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="goals")
    subtasks = relationship("Subtask", back_populates="goal", cascade="all, delete-orphan")
    events = relationship("GoalEvent", back_populates="goal", cascade="all, delete-orphan")
    audit_records = relationship("AuditRecord", back_populates="goal", cascade="all, delete-orphan")


class Subtask(Base):
    __tablename__ = "subtasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    goal_id = Column(String, ForeignKey("goals.id"), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="pending")
    order = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    goal = relationship("Goal", back_populates="subtasks")
    tool_executions = relationship("ToolExecution", back_populates="subtask", cascade="all, delete-orphan")


class GoalEvent(Base):
    __tablename__ = "goal_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    goal_id = Column(String, ForeignKey("goals.id"), nullable=False)
    event_type = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    goal = relationship("Goal", back_populates="events")


class AuditRecord(Base):
    __tablename__ = "audit_records"

    id = Column(String, primary_key=True, default=generate_uuid)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    payload = Column(Text, nullable=True)
    message_id = Column(String, ForeignKey("messages.id"), nullable=True)
    goal_id = Column(String, ForeignKey("goals.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    message = relationship("Message", back_populates="audit_records")
    goal = relationship("Goal", back_populates="audit_records")


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(String, primary_key=True, default=generate_uuid)
    chat_session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False)
    agent_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="idle")
    current_task = Column(Text, nullable=True)
    started_at = Column(DateTime, server_default=func.now())
    ended_at = Column(DateTime, nullable=True)

    chat_session = relationship("ChatSession", back_populates="agent_sessions")


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id = Column(String, primary_key=True, default=generate_uuid)
    subtask_id = Column(String, ForeignKey("subtasks.id"), nullable=True)
    tool_name = Column(String, nullable=False)
    input = Column(Text, nullable=True)
    output = Column(Text, nullable=True)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    subtask = relationship("Subtask", back_populates="tool_executions")


class SkillPackage(Base):
    __tablename__ = "skill_packages"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    author = Column(String, nullable=True)
    manifest_path = Column(String, nullable=False)
    is_installed = Column(Boolean, default=False)
    installed_at = Column(DateTime, nullable=True)

    tools = relationship("ToolDefinition", back_populates="package", cascade="all, delete-orphan")


class ToolDefinition(Base):
    __tablename__ = "tool_definitions"

    id = Column(String, primary_key=True, default=generate_uuid)
    package_id = Column(String, ForeignKey("skill_packages.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    input_schema = Column(Text, nullable=True)
    handler_path = Column(String, nullable=False)

    package = relationship("SkillPackage", back_populates="tools")


class UserLLMConfig(Base):
    __tablename__ = "user_llm_config"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    provider = Column(String, nullable=False)
    encrypted_api_key = Column(Text, nullable=False)
    base_url = Column(String, nullable=True)
    model = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="llm_config")


class UserLLMMode(Base):
    __tablename__ = "user_llm_mode"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    mode = Column(String, nullable=False, default="BACKEND_DEFAULT")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="llm_mode")


class Config(Base):
    __tablename__ = "config"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
