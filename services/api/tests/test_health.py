def test_health(client):
    # /health 는 라우터 prefix("/api") 대상이 아니라 앱에 직접 등록돼 있음(k8s probe 경로와 일치).
    resp = client.get("http://testserver/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
