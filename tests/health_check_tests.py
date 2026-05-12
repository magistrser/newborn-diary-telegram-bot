from fastapi.testclient import TestClient


async def test_health_check(application_client: TestClient) -> None:
    response = application_client.get('/health')

    assert response.status_code == 200
    assert response.text == 'Ok'


async def test_get_metrics(application_client: TestClient) -> None:
    response = application_client.get('/metrics')

    assert response.status_code == 200
    assert 'text/plain' in response.headers['content-type']
