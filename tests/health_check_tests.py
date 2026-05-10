from fastapi.testclient import TestClient

from .lib.fixtures import application_client


async def test_health_check(application_client: TestClient) -> None:
    response = application_client.get('/health')

    assert response.status_code == 200
    assert response.text == 'Ok'
