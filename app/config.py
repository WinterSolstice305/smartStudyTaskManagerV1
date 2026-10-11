import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


# Firebase Web API keys identify a project and are intended for client apps.
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "AIzaSyCLTJL99WCCO8-If_xymFYU2XvbDRit4Ck")
FIREBASE_PROJECT_ID = os.environ.get(
    "FIREBASE_PROJECT_ID", "smartstudytaskmanagerv1"
)
