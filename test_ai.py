import asyncio
import os
from dotenv import load_dotenv

# Load env variables
load_dotenv('.env')

from lib.ai import is_spam

async def main():
    print("Testing API Key:", os.environ.get("GEMINI_API_KEY"))
    text = "Free crypto! DM me 1000% profit guaranteed"
    print(f"Testing message: {text!r}")
    result = await is_spam(text)
    print(f"Result (is_spam): {result}")

if __name__ == "__main__":
    asyncio.run(main())
