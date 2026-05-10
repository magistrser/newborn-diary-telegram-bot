from typing import Generator

from fastapi.testclient import TestClient
from pytest import fixture

from main import app


@fixture
def application_client() -> Generator[TestClient, None, None]:
    with TestClient(app) as client:
        yield client
