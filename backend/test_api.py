import os
import routeros_api
from dotenv import load_dotenv

load_dotenv()

host = os.getenv("MIKROTIK_HOST")
user = os.getenv("MIKROTIK_USER")
password = os.getenv("MIKROTIK_PASS")
port = int(os.getenv("MIKROTIK_PORT", "8728"))

print(f"Connecting to {host}:{port} as {user}...")

try:
    connection = routeros_api.RouterOsApiPool(
        host,
        username=user,
        password=password,
        port=port,
        plaintext_login=True
    )
    api = connection.get_api()
    print("✅ Connection successful! Authentication passed.")
    
    active = api.get_resource("/ppp/active").get()
    print(f"✅ Retrieved active connections: {len(active)} active PPPoE users found.")
    
    connection.disconnect()
except routeros_api.exceptions.RouterOsApiCommunicationError as e:
    print(f"❌ Communication Error (Connection Refused or Timeout): {e}")
    print("Troubleshooting:")
    print("1. Ensure port 8728 is correct and the API service is enabled on the router.")
    print("2. Run '/ip services print' on the Mikrotik terminal to check.")
    print("3. Check if there are any firewall rules blocking the connection from this device.")
except routeros_api.exceptions.RouterOsApiAuthenticationError as e:
    print(f"❌ Authentication Error: {e}")
    print("Troubleshooting:")
    print("1. Check if the username and password are correct.")
    print("2. The router might require a secure login instead of a plaintext login depending on the version.")
    print("   If you have a modern routerOS (v6.43+ or v7), the standard library version of `routeros-api` might struggle with auth. We may need to switch libraries.")
except Exception as e:
    print(f"❌ Unknown Error connecting to MikroTik API: {type(e).__name__}: {e}")
