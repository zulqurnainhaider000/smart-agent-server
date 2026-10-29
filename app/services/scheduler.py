"""
app/services/scheduler.py
-------------------------
Background automation and proactive task scheduler powered by APScheduler.
Modeled after Meta's Muse automation layer, this service executes periodic
and proactive workflows (e.g., Daily Morning Briefing, reminder monitoring, system health)
without blocking client HTTP request threads.
"""

import os
import atexit
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# Scheduler instance running on background daemon threads
scheduler = BackgroundScheduler(daemon=True)


def generate_daily_briefing(app, target_user_id: str = None) -> str:
    """
    Proactively aggregates:
    1. Local weather
    2. Pending notes & reminders count
    3. Major crypto market prices
    4. Top technology news headlines
    Persists the structured briefing into SQLite as a UserNote for the user,
    ensuring it is ready when the user opens their mobile interface.
    """
    with app.app_context():
        try:
            from app.models import User, UserNote
            from app.extensions import db
            from app.services.tools import get_current_time, get_weather
            from app.services.connectors import get_crypto_prices, get_latest_news

            city = os.getenv("BRIEFING_CITY", "London")
            crypto_symbol = os.getenv("BRIEFING_CRYPTO", "bitcoin")
            news_topic = os.getenv("BRIEFING_NEWS_TOPIC", "technology")

            # 1. Resolve Target User
            user = None
            if target_user_id:
                user = User.query.filter(
                    (User.public_id == target_user_id) | (User.username == target_user_id)
                ).first()
            if not user:
                user = User.query.first()

            if not user:
                logger.warning("[Briefing Automation]: No user accounts found in database. Skipping briefing.")
                return "No users found to generate briefing."

            # 2. Check if a briefing was already generated today for this user
            today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            briefing_title = f"[Daily Briefing] - {today_prefix}"
            existing_briefing = UserNote.query.filter_by(
                user_id=user.id,
                title=briefing_title
            ).first()

            # 3. Gather real-time intelligence via agent connectors
            time_info = get_current_time("UTC")
            weather_info = get_weather(city)
            crypto_info = get_crypto_prices(crypto_symbol)
            news_info = get_latest_news(news_topic)

            # Extract top headline from news output
            top_headline = news_info.split("\n")[1] if "\n" in news_info else news_info

            # User's current task count
            pending_notes_count = UserNote.query.filter_by(user_id=user.id).count()

            # 4. Construct Structured Briefing
            briefing_content = (
                f"🌅 Daily Morning Briefing for {user.username}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ {time_info}\n"
                f"🌦️ {weather_info}\n"
                f"🪙 {crypto_info}\n"
                f"📰 Top Story ({news_topic.title()}): {top_headline}\n"
                f"📝 Task Memory: You have {pending_notes_count} note(s)/reminder(s) active in your database.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )

            # 5. Persist or Update Briefing in SQLite
            if existing_briefing:
                existing_briefing.content = briefing_content
            else:
                new_briefing = UserNote(
                    user_id=user.id,
                    title=briefing_title,
                    content=briefing_content
                )
                db.session.add(new_briefing)

            db.session.commit()
            logger.info(f"[Briefing Automation]: Successfully persisted '{briefing_title}' for user '{user.username}'.")
            return briefing_content

        except Exception as err:
            logger.error(f"[Briefing Automation Error]: {err}", exc_info=True)
            return f"Error generating briefing: {str(err)}"


def periodic_reminder_monitor(app):
    """
    Background worker job executed periodically.
    Monitors database state, logs system health pulse, and verifies tasks.
    """
    with app.app_context():
        try:
            from app.models import UserNote
            total_notes = UserNote.query.count()
            logger.info(
                f"[Background Scheduler]: Pulse OK. "
                f"Monitoring {total_notes} persistent user note(s)/reminder(s)."
            )
        except Exception as e:
            logger.error(f"[Background Scheduler Error]: {e}", exc_info=True)


def init_scheduler(app):
    """
    Initializes and starts the background task scheduler with the Flask application context.
    Configures both periodic monitoring and proactive automated daily briefings.
    """
    if not scheduler.running:
        # Avoid double-starting in Flask debug reloader
        if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.config.get("DEBUG"):
            # 1. Periodic pulse & reminder checker (every 60 seconds)
            scheduler.add_job(
                func=periodic_reminder_monitor,
                args=[app],
                trigger=IntervalTrigger(seconds=60),
                id="reminder_monitor_job",
                name="Periodic Reminder & System Pulse Monitor",
                replace_existing=True,
            )

            # 2. Automated Briefing Generator (Scheduled to trigger every 4 hours or daily at 8:00 AM)
            scheduler.add_job(
                func=generate_daily_briefing,
                args=[app],
                trigger=IntervalTrigger(hours=4),
                id="daily_briefing_job",
                name="Automated Proactive Morning Intelligence Briefing",
                replace_existing=True,
            )

            scheduler.start()
            logger.info("APScheduler background engine started successfully (Jobs: Monitor + Briefing).")

            # Run an initial briefing generation on background startup
            scheduler.add_job(
                func=generate_daily_briefing,
                args=[app],
                id="startup_briefing_job",
                name="Initial Startup Briefing",
                replace_existing=True
            )

            # Ensure graceful shutdown on server exit
            atexit.register(lambda: scheduler.shutdown(wait=False) if scheduler.running else None)
        else:
            logger.debug("Scheduler start deferred to Werkzeug main process.")
