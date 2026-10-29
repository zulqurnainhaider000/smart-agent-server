"""
app/models.py
-------------
Database models for User and ChatHistory / Messages.
Includes input sanitization, field-level validation hooks, UUID public identifiers,
and foreign key integrity constraints.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import func
from sqlalchemy.orm import validates

from app.extensions import db
from app.utils.validators import (
    sanitize_text,
    validate_username,
    validate_email,
    validate_session_id,
)


class User(db.Model):
    """
    User Model
    Stores user account information and secure public UUID identifiers.
    """
    __tablename__ = "users"

    # Internal primary key (fast integer indexing for foreign keys)
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Secure public identifier (prevents sequential ID enumeration via APIs)
    public_id = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
        index=True
    )

    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Timestamps
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=True
    )

    # Relationship to ChatHistory with automatic cascade deletion
    chat_history = db.relationship(
        "ChatHistory",
        backref="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="ChatHistory.created_at.asc()"
    )

    # Relationship to UserNote with automatic cascade deletion
    notes = db.relationship(
        "UserNote",
        backref="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="UserNote.created_at.desc()"
    )

    # -------------------------------------------------------------------------
    # Input Validation & Sanitization Hooks (ORM Level)
    # -------------------------------------------------------------------------
    @validates("username")
    def validate_and_clean_username(self, key, value):
        return validate_username(value)

    @validates("email")
    def validate_and_clean_email(self, key, value):
        if value is None:
            return None
        return validate_email(value)

    def to_dict(self) -> dict:
        """Serializes safe user attributes for JSON responses."""
        return {
            "id": self.public_id,
            "username": self.username,
            "email": self.email,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<User username='{self.username}' public_id='{self.public_id}'>"


class ChatHistory(db.Model):
    """
    ChatHistory / Message Model
    Stores chat turns between the user and the AI agent, conversation session identifiers,
    timestamps, and token usage metadata.
    """
    __tablename__ = "chat_history"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Foreign key referencing internal user id
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Conversation session ID to allow multiple separate chat threads per user
    session_id = db.Column(
        db.String(64),
        nullable=False,
        default=lambda: str(uuid.uuid4()),
        index=True
    )

    # Message payloads (sanitized text)
    user_message = db.Column(db.Text, nullable=False)
    agent_response = db.Column(db.Text, nullable=True)

    # Optional reference to uploaded image path in instance/uploads/images/
    image_path = db.Column(db.String(255), nullable=True)

    # Optional reference to uploaded audio recording path in instance/uploads/audio/
    audio_path = db.Column(db.String(255), nullable=True)

    # Metadata for cost & latency tracking
    tokens_used = db.Column(db.Integer, default=0, nullable=False)

    # Timestamp with index for rapid chronological sorting
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
        index=True
    )

    # -------------------------------------------------------------------------
    # Input Validation & Sanitization Hooks (ORM Level)
    # -------------------------------------------------------------------------
    @validates("user_message")
    def validate_and_sanitize_user_message(self, key, value):
        return sanitize_text(value)

    @validates("agent_response")
    def validate_and_sanitize_agent_response(self, key, value):
        if value is None:
            return None
        return sanitize_text(value)

    @validates("session_id")
    def validate_and_clean_session_id(self, key, value):
        return validate_session_id(value)

    def to_dict(self) -> dict:
        """Serializes chat turn for JSON API responses."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user.public_id if self.user else None,
            "user_message": self.user_message,
            "agent_response": self.agent_response,
            "image_path": self.image_path,
            "audio_path": self.audio_path,
            "tokens_used": self.tokens_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


    def to_llm_messages(self) -> list:
        """
        Converts the turn into standard multi-turn LLM message format.
        Preserves knowledge of image attachment without resending full binary payloads.
        """
        user_content = self.user_message
        if self.image_path:
            user_content = f"[Attached Image: {self.image_path}]\n{self.user_message}"

        messages = [{"role": "user", "content": user_content}]
        if self.agent_response:
            messages.append({"role": "assistant", "content": self.agent_response})
        return messages


    def __repr__(self) -> str:
        return f"<ChatHistory id={self.id} session_id='{self.session_id}' user_id={self.user_id}>"


# Semantic alias so developers can refer to it as ChatMessage or ChatHistory
ChatMessage = ChatHistory


class UserNote(db.Model):
    """
    UserNote / Reminder Model
    Stores persistent notes, reminders, facts, or tasks created by or for the user.
    """
    __tablename__ = "user_notes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    title = db.Column(db.String(128), nullable=False)
    content = db.Column(db.Text, nullable=False)

    # Optional reminder timestamp and completion state
    reminder_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)

    # Timestamps
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
        index=True
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=True
    )

    # Input validation hooks
    @validates("title")
    def validate_and_clean_title(self, key, value):
        return sanitize_text(value, max_length=128)

    @validates("content")
    def validate_and_clean_content(self, key, value):
        return sanitize_text(value, max_length=16384)

    def to_dict(self) -> dict:
        """Serializes note for JSON responses or tool summaries."""
        return {
            "id": self.id,
            "user_id": self.user.public_id if self.user else None,
            "title": self.title,
            "content": self.content,
            "reminder_at": self.reminder_at.isoformat() if self.reminder_at else None,
            "is_completed": self.is_completed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<UserNote id={self.id} title='{self.title}' user_id={self.user_id}>"


# Semantic alias
Reminder = UserNote
