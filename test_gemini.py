import os
from google import genai
from google.genai import types

API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")

try:
    print("Testing Gemini API...")
    client = genai.Client(api_key=API_KEY)
    
    # Send a simple text prompt to test authentication and basic functionality
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents="Hello, testing authentication. Reply 'Success' if you get this."
    )
    print("Response:")
    print(response.text)
except Exception as e:
    print(f"Error: {str(e)}")
