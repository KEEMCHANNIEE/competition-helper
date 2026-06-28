def test_list_competitions_returns_repo_items(client):
    resp = client.get("/competitions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["title"] == "AI 공모전"


def test_list_competitions_respects_limit(client):
    resp = client.get("/competitions", params={"limit": 1})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_competitions_limit_validation(client):
    assert client.get("/competitions", params={"limit": 0}).status_code == 422
    assert client.get("/competitions", params={"limit": 101}).status_code == 422
