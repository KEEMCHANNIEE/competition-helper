from app.queue import RECOMMEND_QUEUE_KEY


def test_post_recommend_enqueues_and_returns_job_id(client, fake_redis):
    resp = client.post("/recommend", json={"limit": 3})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert job_id

    # Redis 큐 계약: 키와 페이로드가 정확히 들어갔는지.
    queued = fake_redis.lists[RECOMMEND_QUEUE_KEY]
    assert len(queued) == 1
    assert job_id in queued[0]
    assert '"limit":3' in queued[0].replace(" ", "")


def test_post_recommend_reuses_active_job(client, fake_redis):
    first = client.post("/recommend", json={"limit": 5}).json()["job_id"]
    second = client.post("/recommend", json={"limit": 5}).json()["job_id"]
    assert first == second
    # 재사용이므로 큐에는 한 번만 들어가야 한다.
    assert len(fake_redis.lists[RECOMMEND_QUEUE_KEY]) == 1


def test_get_recommend_status(client):
    job_id = client.post("/recommend", json={"limit": 2}).json()["job_id"]
    resp = client.get(f"/recommend/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert body["status"] == "queued"
    assert body["results"] == []


def test_get_recommend_missing_job_404(client):
    assert client.get("/recommend/does-not-exist").status_code == 404
