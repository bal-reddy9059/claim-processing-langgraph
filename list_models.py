"""Lists all available Gemini models for your API key."""
import os
from dotenv import load_dotenv
load_dotenv()

from google import genai

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

print("Available models:\n")
for model in client.models.list():
    print(f"  {model.name}")
