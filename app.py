"""
app.py
------
Main application runner and WSGI entry point for the personal AI agent backend.

Usage:
    - Development:
        python app.py
    - Flask CLI:
        flask --app app.py init-db    # Create database schema
        flask --app app.py run --port=5000
    - Production (Gunicorn / Waitress):
        gunicorn "app:app" -w 4 -b 0.0.0.0:5000
"""

from app import create_app
from app.extensions import db
from config import get_config

# Instantiate application via Application Factory
app = create_app()

if __name__ == "__main__":
    config = get_config()
    host = getattr(config, "HOST", "0.0.0.0")
    port = getattr(config, "PORT", 5000)
    debug = getattr(config, "DEBUG", True)

    # Safely ensure database file and tables exist before listening for requests
    with app.app_context():
        db.create_all()
        # Verify and migrate chat_history schema for image_path
        try:
            with db.engine.connect() as conn:
                res = conn.execute(db.text("PRAGMA table_info(chat_history)")).fetchall()
                existing_cols = [row[1] for row in res]
                if "image_path" not in existing_cols:
                    conn.execute(db.text("ALTER TABLE chat_history ADD COLUMN image_path VARCHAR(255)"))
                    conn.commit()
                    app.logger.info("Migrated chat_history: added 'image_path' column.")
                if "audio_path" not in existing_cols:
                    conn.execute(db.text("ALTER TABLE chat_history ADD COLUMN audio_path VARCHAR(255)"))
                    conn.commit()
                    app.logger.info("Migrated chat_history: added 'audio_path' column.")
        except Exception as mig_err:
            app.logger.warning(f"Database schema migration check note: {mig_err}")


        app.logger.info("Database verified and tables initialized.")


    app.logger.info(f"Starting server on http://{host}:{port} [Debug: {debug}]")
    app.run(host=host, port=port, debug=debug)
