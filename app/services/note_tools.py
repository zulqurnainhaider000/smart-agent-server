"""
app/services/note_tools.py
--------------------------
Persistent user notes and memory management tools for the personal AI agent.
Allows the agent to remember facts, todo items, notes, and reminders across sessions
by interfacing directly with the SQLite database via SQLAlchemy.
"""

import logging
from typing import Optional
from app.extensions import db
from app.models import User, UserNote

logger = logging.getLogger(__name__)


def _resolve_user(user_identifier: str) -> Optional[User]:
    """Resolves a User instance by public_id or username."""
    if not user_identifier:
        return None
    ident = str(user_identifier).strip()
    return User.query.filter(
        (User.public_id == ident) | (User.username == ident)
    ).first()


def save_user_note(user_id: str, title: str, content: str) -> str:
    """
    Saves a persistent note, fact, reminder, or memory for a user to SQLite.

    :param user_id: The user's public UUID or username.
    :param title: Short, descriptive summary or subject for the note.
    :param content: Detailed body or text content to remember.
    :return: Confirmation string with note ID.
    """
    logger.info(f"save_user_note called for user='{user_id}' with title='{title}'")

    if not title or not content:
        return "Error: Both 'title' and 'content' are required to save a note."

    try:
        user = _resolve_user(user_id)
        if not user:
            # Fallback: find the first active user if default
            user = User.query.first()
            if not user:
                return f"Error: User '{user_id}' could not be resolved."

        note = UserNote(
            user_id=user.id,
            title=title.strip()[:128],
            content=content.strip()
        )
        db.session.add(note)
        db.session.commit()

        logger.info(f"Successfully saved note #{note.id} for user {user.username}")
        return (
            f"Successfully saved note #{note.id}: '{note.title}'. "
            f"Content: \"{note.content}\""
        )

    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to save user note: {e}", exc_info=True)
        return f"Database Error saving note: {str(e)}"


def get_user_notes(user_id: str) -> str:
    """
    Retrieves all persistent notes, reminders, and saved information for a user.

    :param user_id: The user's public UUID or username.
    :return: Formatted list of all notes or a message if empty.
    """
    logger.info(f"get_user_notes called for user='{user_id}'")

    try:
        user = _resolve_user(user_id)
        if not user:
            user = User.query.first()
            if not user:
                return f"Error: User '{user_id}' could not be resolved."

        notes = (
            UserNote.query.filter_by(user_id=user.id)
            .order_by(UserNote.created_at.desc())
            .all()
        )

        if not notes:
            return f"No saved notes or reminders found for user '{user.username}'."

        formatted = [f"Found {len(notes)} saved note(s) for user '{user.username}':"]
        for note in notes:
            created_str = (
                note.created_at.strftime("%Y-%m-%d %I:%M %p")
                if note.created_at
                else "N/A"
            )
            formatted.append(
                f"- [Note ID {note.id}] '{note.title}': {note.content} (Saved: {created_str})"
            )

        return "\n".join(formatted)

    except Exception as e:
        logger.error(f"Failed to fetch user notes: {e}", exc_info=True)
        return f"Database Error retrieving notes: {str(e)}"


def delete_user_note(user_id: str, note_id: int) -> str:
    """
    Deletes a specific note or reminder by its ID for a user.

    :param user_id: The user's public UUID or username.
    :param note_id: The unique integer ID of the note to delete.
    :return: Confirmation of deletion or error message.
    """
    logger.info(f"delete_user_note called for user='{user_id}', note_id={note_id}")

    try:
        user = _resolve_user(user_id)
        if not user:
            user = User.query.first()
            if not user:
                return f"Error: User '{user_id}' could not be resolved."

        try:
            target_id = int(note_id)
        except (ValueError, TypeError):
            return f"Error: note_id must be a valid integer, received '{note_id}'."

        note = UserNote.query.filter_by(id=target_id, user_id=user.id).first()
        if not note:
            return f"Note #{target_id} does not exist or does not belong to user '{user.username}'."

        deleted_title = note.title
        db.session.delete(note)
        db.session.commit()

        logger.info(f"Successfully deleted note #{target_id} ('{deleted_title}')")
        return f"Successfully deleted note #{target_id} ('{deleted_title}')."

    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to delete user note #{note_id}: {e}", exc_info=True)
        return f"Database Error deleting note: {str(e)}"
