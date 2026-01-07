#!/usr/bin/env python3
"""Debug script to identify why Google OAuth token verification is hanging."""

import os
import sys
import time
import socket
import ssl
from urllib.parse import urlparse

print("=" * 80)
print("GOOGLE OAUTH DEBUGGING SCRIPT")
print("=" * 80)
print()

# 1. Check Environment Variables
print("1. ENVIRONMENT VARIABLES")
print("-" * 80)
proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 
              'NO_PROXY', 'no_proxy', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE']
for var in proxy_vars:
    value = os.environ.get(var, 'Not set')
    print(f"  {var}: {value}")
print()

# 2. Test Basic Network Connectivity
print("2. NETWORK CONNECTIVITY TEST")
print("-" * 80)
try:
    sock = socket.create_connection(('www.googleapis.com', 443), timeout=5)
    sock.close()
    print("  ✓ TCP connection to www.googleapis.com:443 successful")
except socket.timeout:
    print("  ✗ TCP connection TIMEOUT (5s)")
except Exception as e:
    print(f"  ✗ TCP connection FAILED: {e}")
print()

# 3. Test DNS Resolution
print("3. DNS RESOLUTION")
print("-" * 80)
try:
    ip = socket.gethostbyname('www.googleapis.com')
    print(f"  ✓ DNS resolution: www.googleapis.com -> {ip}")
except Exception as e:
    print(f"  ✗ DNS resolution FAILED: {e}")
print()

# 4. Test SSL Certificate
print("4. SSL CERTIFICATE TEST")
print("-" * 80)
try:
    context = ssl.create_default_context()
    with socket.create_connection(('www.googleapis.com', 443), timeout=5) as sock:
        with context.wrap_socket(sock, server_hostname='www.googleapis.com') as ssock:
            cert = ssock.getpeercert()
            print(f"  ✓ SSL handshake successful")
            print(f"    Subject: {cert.get('subject', 'N/A')}")
            print(f"    Issuer: {cert.get('issuer', 'N/A')}")
except Exception as e:
    print(f"  ✗ SSL handshake FAILED: {e}")
print()

# 5. Test with urllib (what google.auth.transport.requests uses internally)
print("5. URLLIB TEST (what google.auth uses)")
print("-" * 80)
try:
    import urllib.request
    import urllib.error
    
    url = "https://www.googleapis.com/oauth2/v3/certs"
    print(f"  Testing: {url}")
    start = time.time()
    
    req = urllib.request.Request(url)
    # Check if urllib is using a proxy
    proxy_handler = urllib.request.getproxies()
    if proxy_handler:
        print(f"  ⚠️  urllib detected proxies: {proxy_handler}")
        # Try without proxy
        opener = urllib.request.build_opener()
        opener.addheaders = [('User-Agent', 'Python-urllib')]
    else:
        opener = urllib.request.build_opener()
        opener.addheaders = [('User-Agent', 'Python-urllib')]
    
    with opener.open(req, timeout=10) as response:
        elapsed = time.time() - start
        data = response.read()
        print(f"  ✓ Success! Status: {response.status}, Time: {elapsed:.2f}s")
        print(f"    Response length: {len(data)} bytes")
        print(f"    Content-Type: {response.headers.get('Content-Type', 'N/A')}")
except urllib.error.URLError as e:
    elapsed = time.time() - start if 'start' in locals() else 0
    print(f"  ✗ URLError after {elapsed:.2f}s: {e}")
    if hasattr(e, 'reason'):
        print(f"    Reason: {e.reason}")
except Exception as e:
    elapsed = time.time() - start if 'start' in locals() else 0
    print(f"  ✗ FAILED after {elapsed:.2f}s: {type(e).__name__}: {e}")
print()

# 6. Test IPv4 vs IPv6 preference
print("6. IPV4 vs IPV6 TEST")
print("-" * 80)
try:
    import socket
    
    # Get all IP addresses
    addr_info = socket.getaddrinfo('www.googleapis.com', 443, 
                                   socket.AF_UNSPEC, socket.SOCK_STREAM)
    ipv4_addrs = [a[4][0] for a in addr_info if a[0] == socket.AF_INET]
    ipv6_addrs = [a[4][0] for a in addr_info if a[0] == socket.AF_INET6]
    
    print(f"  IPv4 addresses: {ipv4_addrs[:3]}... ({len(ipv4_addrs)} total)")
    print(f"  IPv6 addresses: {ipv6_addrs[:3]}... ({len(ipv6_addrs)} total)")
    
    # Test IPv4 connection speed
    if ipv4_addrs:
        start = time.time()
        try:
            sock = socket.create_connection((ipv4_addrs[0], 443), timeout=5)
            elapsed = time.time() - start
            sock.close()
            print(f"  ✓ IPv4 connection: {elapsed:.3f}s")
        except Exception as e:
            print(f"  ✗ IPv4 connection failed: {e}")
    
    # Test IPv6 connection speed
    if ipv6_addrs:
        start = time.time()
        try:
            sock = socket.create_connection((ipv6_addrs[0], 443), timeout=5)
            elapsed = time.time() - start
            sock.close()
            print(f"  ✓ IPv6 connection: {elapsed:.3f}s")
        except Exception as e:
            print(f"  ✗ IPv6 connection failed: {e}")
    
    # Force IPv4 for urllib test
    print(f"\n  Testing urllib with IPv4 preference...")
    import urllib.request
    import urllib.error
    
    # Monkey patch socket to prefer IPv4
    original_getaddrinfo = socket.getaddrinfo
    def getaddrinfo_ipv4(*args, **kwargs):
        results = original_getaddrinfo(*args, **kwargs)
        # Sort to prefer IPv4
        ipv4_results = [r for r in results if r[0] == socket.AF_INET]
        ipv6_results = [r for r in results if r[0] == socket.AF_INET6]
        return ipv4_results + ipv6_results
    
    socket.getaddrinfo = getaddrinfo_ipv4
    
    url = "https://www.googleapis.com/oauth2/v3/certs"
    start = time.time()
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            elapsed = time.time() - start
            data = response.read()
            print(f"  ✓ IPv4-preferenced urllib: {elapsed:.2f}s")
    except Exception as e:
        elapsed = time.time() - start
        print(f"  ✗ IPv4-preferenced urllib failed: {e} after {elapsed:.2f}s")
    finally:
        socket.getaddrinfo = original_getaddrinfo
    
except Exception as e:
    print(f"  ✗ IP version test FAILED: {type(e).__name__}: {e}")
print()

# 7. Test with google.auth.transport.requests (actual usage)
print("7. GOOGLE.AUTH.TRANSPORT.REQUESTS TEST (simulating actual usage)")
print("-" * 80)
try:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    
    # We need a dummy token to test - but let's just test the request object
    print(f"  Testing Request object creation and underlying HTTP client")
    start = time.time()
    req = google_requests.Request()
    print(f"  Request object created: {type(req)}")
    
    # Check what's inside
    if hasattr(req, '_http'):
        print(f"  Has _http: {type(req._http)}")
    if hasattr(req, '_session'):
        print(f"  Has _session: {type(req._session)}")
    
    # The Request object wraps a requests.Session
    # Let's test the underlying session directly
    import requests
    url = "https://www.googleapis.com/oauth2/v3/certs"
    print(f"  Testing with requests library directly: {url}")
    start = time.time()
    response = requests.get(url, timeout=10)
    elapsed = time.time() - start
    print(f"  ✓ requests library: Status {response.status_code}, Time: {elapsed:.2f}s")
    
except Exception as e:
    elapsed = time.time() - start if 'start' in locals() else 0
    print(f"  ✗ FAILED after {elapsed:.2f}s: {type(e).__name__}: {e}")
    import traceback
    print(f"    Traceback:")
    for line in traceback.format_exc().split('\n'):
        if line.strip():
            print(f"      {line}")
print()

# 8. Check Python's SSL context
print("8. SSL CONTEXT INFO")
print("-" * 80)
try:
    import ssl
    ctx = ssl.create_default_context()
    print(f"  Default SSL context created")
    print(f"  Protocol: {ctx.protocol}")
    print(f"  Check hostname: {ctx.check_hostname}")
    print(f"  Verify mode: {ctx.verify_mode}")
    
    # Check certificate locations
    try:
        import certifi
        print(f"  certifi location: {certifi.where()}")
        if os.path.exists(certifi.where()):
            print(f"  ✓ certifi certificate file exists")
        else:
            print(f"  ✗ certifi certificate file NOT FOUND")
    except ImportError:
        print(f"  certifi not installed")
except Exception as e:
    print(f"  ✗ SSL context check FAILED: {e}")
print()

# 9. Check if running in Docker/container
print("9. ENVIRONMENT CHECK")
print("-" * 80)
if os.path.exists('/.dockerenv'):
    print("  ⚠️  Running in Docker container")
else:
    print("  Running on host (not Docker)")

# Check Python version
print(f"  Python version: {sys.version}")
print(f"  Python executable: {sys.executable}")
print()

print("=" * 80)
print("DEBUGGING COMPLETE")
print("=" * 80)

