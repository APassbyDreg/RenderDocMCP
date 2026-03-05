"""
RenderDoc Bridge Client
Communicates with the RenderDoc extension via file-based IPC.
"""

import json
import os
import tempfile
import time
import uuid
from typing import Any


# IPC directory (must match renderdoc_extension/socket_server.py)
IPC_DIR = os.path.join(tempfile.gettempdir(), "renderdoc_mcp")
LOG_FILE = os.path.join(IPC_DIR, "client.log")
REQUEST_FILE = os.path.join(IPC_DIR, "request.json")
RESPONSE_FILE = os.path.join(IPC_DIR, "response.json")
REQUEST_LOCK_FILE = os.path.join(IPC_DIR, "request.lock")
RESPONSE_LOCK_FILE = os.path.join(IPC_DIR, "response.lock")


class RenderDocBridgeError(Exception):
    """Error communicating with RenderDoc bridge"""

    pass


class RenderDocBridge:
    """Client for communicating with RenderDoc extension via file-based IPC"""

    def __init__(self, host: str = "127.0.0.1", port: int = 19876):
        # host/port are kept for API compatibility but not used
        self.host = host
        self.port = port
        self.timeout = 30.0  # seconds

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Call a method on the RenderDoc extension"""
        # Check if IPC directory exists
        if not os.path.exists(IPC_DIR):
            raise RenderDocBridgeError(
                f"Cannot connect to RenderDoc MCP Bridge at {self.host}:{self.port}. "
                "Make sure RenderDoc is running with the MCP Bridge extension loaded."
                " IPC directory not found: %s" % IPC_DIR
            )

        request = {
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params or {},
        }

        try:
            # Clean up any stale response file
            if os.path.exists(RESPONSE_FILE):
                os.remove(RESPONSE_FILE)

            # Create lock file to signal we're writing
            with open(REQUEST_LOCK_FILE, "w") as f:
                f.write("lock")

            # Write request
            with open(REQUEST_FILE, "w", encoding="utf-8") as f:
                json.dump(request, f)

            # Remove lock file to signal write complete
            os.remove(REQUEST_LOCK_FILE)

            # Wait for response
            start_time = time.time()
            while True:
                if os.path.exists(RESPONSE_FILE):
                    # Wait until response lock file is removed (RDC finished writing)
                    if os.path.exists(RESPONSE_LOCK_FILE):
                        time.sleep(0.05)
                        continue

                    # Read response
                    with open(RESPONSE_FILE, "r", encoding="utf-8") as f:
                        response = json.load(f)

                    # Clean up response file
                    os.remove(RESPONSE_FILE)

                    if "error" in response:
                        return response
                    else:
                        return response.get("result")

                # Check timeout
                if time.time() - start_time > self.timeout:
                    raise RenderDocBridgeError("Request timed out")

                # Poll interval
                time.sleep(0.05)

        except RenderDocBridgeError:
            raise
        except Exception as e:
            raise RenderDocBridgeError(f"Communication error: {e}")
