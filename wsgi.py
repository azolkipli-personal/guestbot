"""WSGI entrypoint for Gunicorn/Render: `gunicorn wsgi:app`."""
import os

from dotenv import load_dotenv

from app import create_app

load_dotenv()
app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
