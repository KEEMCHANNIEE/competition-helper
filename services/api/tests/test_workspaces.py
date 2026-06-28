from keenee_core.models import Recommendation, User


def test_create_workspace(client):
    resp = client.post("/workspaces", json={"name": "팀A"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "팀A"
    assert "id" in body


def test_get_workspace_as_member(client):
    ws_id = client.post("/workspaces", json={"name": "팀A"}).json()["id"]
    resp = client.get(f"/workspaces/{ws_id}")
    assert resp.status_code == 200
    assert resp.json()["recommendations"] == []


def test_get_workspace_missing_404(client):
    assert client.get("/workspaces/9999").status_code == 404


def test_add_member_and_attach_recommendations(client, db_session, test_user):
    # 초대 대상 사용자 준비.
    other = User(email="other@keenee.dev", name="동료", interests=[], skills=[])
    db_session.add(other)
    # 추천 1건(현재 유저 소유) 준비.
    reco = Recommendation(
        job_id="j1",
        user_id=test_user.id,
        competition_id=10,
        title="공모전X",
        reason="딱 맞음",
    )
    db_session.add(reco)
    db_session.commit()
    reco_id = reco.id

    ws_id = client.post("/workspaces", json={"name": "팀A"}).json()["id"]

    # owner 가 멤버 초대.
    m = client.post(
        f"/workspaces/{ws_id}/members",
        json={"email": "other@keenee.dev", "role": "member"},
    )
    assert m.status_code == 201

    # 중복 초대는 409.
    dup = client.post(
        f"/workspaces/{ws_id}/members", json={"email": "other@keenee.dev"}
    )
    assert dup.status_code == 409

    # 추천을 팀에 저장.
    attach = client.post(
        f"/workspaces/{ws_id}/recommendations",
        json={"recommendation_ids": [reco_id]},
    )
    assert attach.status_code == 200
    assert attach.json()["attached"] == 1

    # 팀 조회 시 추천이 보인다.
    detail = client.get(f"/workspaces/{ws_id}").json()
    assert len(detail["recommendations"]) == 1
    assert detail["recommendations"][0]["competition_id"] == 10


def test_add_member_unknown_email_404(client):
    ws_id = client.post("/workspaces", json={"name": "팀A"}).json()["id"]
    resp = client.post(
        f"/workspaces/{ws_id}/members", json={"email": "ghost@keenee.dev"}
    )
    assert resp.status_code == 404
