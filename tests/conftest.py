import os
import base64
import struct
import zlib
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test_task_management.db"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-long-enough"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


def valid_profile_image() -> str:
    raw = b"".join(b"\x00" + b"\x65\x8f\xd0" * 128 for _ in range(128))
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 128, 128, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    Path("test_task_management.db").unlink(missing_ok=True)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    client.post(
        "/auth/register",
        json={
            "name": "Test User",
            "email": "test@example.com",
            "password": "securepass123",
        },
    )
    response = client.post(
        "/auth/login",
        data={"username": "test@example.com", "password": "securepass123"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
