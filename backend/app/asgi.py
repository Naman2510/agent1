"""ASGI entrypoint: `uvicorn app.asgi:app`.

Separate from `app.main` so importing the factory never requires a configured environment — tests
build their own app with their own settings.
"""

from app.main import create_app

app = create_app()
