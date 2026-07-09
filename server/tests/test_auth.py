"""Auth tests: valid/invalid/missing token, and /v1/health needing none."""

from fastapi.testclient import TestClient


def test_health_requires_no_auth(api_client: TestClient) -> None:
    response = api_client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_models_rejects_missing_token(api_client: TestClient) -> None:
    response = api_client.get("/v1/models")
    assert response.status_code == 401


def test_models_rejects_wrong_token(api_client: TestClient) -> None:
    response = api_client.get("/v1/models", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_models_accepts_valid_token(api_client: TestClient, auth_headers: dict) -> None:
    response = api_client.get("/v1/models", headers=auth_headers)
    assert response.status_code == 200


def test_embed_rejects_missing_token(api_client: TestClient) -> None:
    response = api_client.post("/v1/embed", json={"model": "m", "input": ["x"]})
    assert response.status_code == 401


def test_chat_rejects_missing_token(api_client: TestClient) -> None:
    response = api_client.post("/v1/chat", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 401
