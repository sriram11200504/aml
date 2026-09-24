import pytest
import socket
import threading
import time
import sys
from pathlib import Path

# Add mock-model-service to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "mock-model-service"))

_server_thread = None

def is_port_open(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0

def pytest_addoption(parser):
    parser.addoption("--model-url", action="store", default="http://localhost:8200", help="Model service URL")

@pytest.fixture(scope="session", autouse=True)
def ensure_model_server(request):
    global _server_thread
    url = request.config.getoption("--model-url", default="http://localhost:8200")
    if "localhost" in url or "127.0.0.1" in url:
        port = 8200
        if not is_port_open("127.0.0.1", port):
            import uvicorn
            from main import app
            config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", loop="asyncio")
            server = uvicorn.Server(config)
            _server_thread = threading.Thread(target=server.run, daemon=True)
            _server_thread.start()
            for _ in range(50):
                if is_port_open("127.0.0.1", port):
                    break
                time.sleep(0.1)
            time.sleep(0.5)

@pytest.fixture
def model_url(request):
    try:
        url = request.config.getoption("--model-url")
        if url:
            return url
    except Exception:
        pass
    return "http://localhost:8200"
