#!/usr/bin/env python
"""Test script to verify OpenAI API connection."""

import asyncio
import sys
from app.config import settings
from openai import AsyncOpenAI
import structlog

# Configure logging
logger = structlog.get_logger()

async def test_openai_connection():
    """Test the OpenAI API connection."""
    try:
        # Show partial API key for verification
        key_start = settings.openai_api_key[:10] if len(settings.openai_api_key) > 10 else "***"
        key_end = settings.openai_api_key[-4:] if len(settings.openai_api_key) > 4 else "***"
        print(f"Using API key: {key_start}...{key_end}")

        # Initialize the client with simpler settings
        print("Initializing OpenAI client...")
        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=60.0  # Overall timeout in seconds
        )
        print("OpenAI client initialized successfully")

        # Simple test message
        test_message = "Hello, this is a test message to verify OpenAI API connectivity."

        # Test with a simple completion
        print("Sending test request to OpenAI API...")

        # Set up a retry mechanism
        max_retries = 3
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                print(f"Attempt {attempt + 1}/{max_retries}...")

                response = await client.chat.completions.create(
                    model="gpt-4o-mini",  # Using a more widely available model for testing
                    messages=[{"role": "user", "content": test_message}],
                    max_tokens=50,
                    temperature=0.7,
                )

                print(f"Response received! ID: {response.id}")
                print(f"Response content: {response.choices[0].message.content}")
                print("\nAPI connection is working correctly!")
                return True

            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {str(e)}")

                # If we're not on the last attempt, wait and retry
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    print(f"Waiting {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)
                else:
                    # Last attempt failed
                    raise

    except Exception as e:
        print(f"\n❌ Error connecting to OpenAI API: {str(e)}")
        print(f"Exception type: {type(e).__name__}")

        # Network diagnostics
        print("\nPerforming network diagnostics...")
        try:
            import socket
            api_host = "api.openai.com"
            print(f"DNS lookup for {api_host}: {socket.gethostbyname(api_host)}")

            # Test connectivity
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            result = s.connect_ex((api_host, 443))
            if result == 0:
                print(f"TCP connection to {api_host}:443 successful")
            else:
                print(f"TCP connection to {api_host}:443 failed with error code {result}")
            s.close()
        except Exception as net_error:
            print(f"Network diagnostic error: {str(net_error)}")

        print("\nPossible issues to check:")
        print("1. API key might be invalid or expired")
        print("2. Network connectivity problems - check your internet connection")
        print("3. Firewall or proxy settings might be blocking the connection")
        print("4. OpenAI service might be experiencing downtime")
        print("5. The model you're trying to use might be unavailable")
        print("\nSuggested solutions:")
        print("1. Check if you can access https://api.openai.com in a browser")
        print("2. Try a different network connection")
        print("3. Check if a VPN or proxy is required for your network")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_openai_connection())
    sys.exit(0 if success else 1)
