from contest_helper_core.models import Recommendation, User


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
    other = User(email="other@contest-helper.dev", name="동료", interests=[], skills=[])
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
        json={"email": "other@contest-helper.dev", "role": "member"},
    )
    assert m.status_code == 201

    # 중복 초대는 409.
    dup = client.post(
        f"/workspaces/{ws_id}/members", json={"email": "other@contest-helper.dev"}
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
        f"/workspaces/{ws_id}/members", json={"email": "ghost@contest-helper.dev"}
    )
    assert resp.status_code == 404


def test_create_workspace_with_contest_id(client):
    resp = client.post("/workspaces", json={"name": "팀B", "contest_id": 42})
    assert resp.status_code == 201
    assert resp.json()["contest_id"] == 42


def test_add_and_list_tasks(client):
    ws_id = client.post("/workspaces", json={"name": "팀A"}).json()["id"]

    # 멤버(owner)가 할 일 추가.
    t1 = client.post(
        f"/workspaces/{ws_id}/tasks",
        json={"title": "기획서 작성", "week_no": 2},
    )
    assert t1.status_code == 201
    assert t1.json()["title"] == "기획서 작성"

    client.post(
        f"/workspaces/{ws_id}/tasks",
        json={"title": "아이디어 회의", "week_no": 1},
    )

    # week_no 순으로 정렬되어 나온다.
    tasks = client.get(f"/workspaces/{ws_id}/tasks").json()
    assert [t["week_no"] for t in tasks] == [1, 2]
    assert tasks[0]["title"] == "아이디어 회의"


def test_update_task_status_toggles_done(client):
    ws_id = client.post("/workspaces", json={"name": "팀A"}).json()["id"]
    task_id = client.post(
        f"/workspaces/{ws_id}/tasks", json={"title": "기획서 작성"}
    ).json()["id"]

    resp = client.patch(
        f"/workspaces/{ws_id}/tasks/{task_id}", json={"status": "done"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"

    # 다시 미완료로.
    resp2 = client.patch(
        f"/workspaces/{ws_id}/tasks/{task_id}", json={"status": "todo"}
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "todo"


def test_update_task_status_rejects_invalid_status(client):
    ws_id = client.post("/workspaces", json={"name": "팀A"}).json()["id"]
    task_id = client.post(
        f"/workspaces/{ws_id}/tasks", json={"title": "기획서 작성"}
    ).json()["id"]

    resp = client.patch(
        f"/workspaces/{ws_id}/tasks/{task_id}", json={"status": "in_progress"}
    )
    assert resp.status_code == 400


def test_update_task_status_missing_task_404(client):
    ws_id = client.post("/workspaces", json={"name": "팀A"}).json()["id"]
    resp = client.patch(
        f"/workspaces/{ws_id}/tasks/9999", json={"status": "done"}
    )
    assert resp.status_code == 404


def test_update_task_status_requires_membership(client, db_session, test_user):
    from contest_helper_core.models import Task, User, Workspace, WorkspaceMember

    other = User(email="boss2@contest-helper.dev", name="사장2", interests=[], skills=[])
    db_session.add(other)
    db_session.commit()
    ws = Workspace(name="외부팀", owner_id=other.id)
    db_session.add(ws)
    db_session.commit()
    db_session.add(WorkspaceMember(workspace_id=ws.id, user_id=other.id, role="owner"))
    task = Task(workspace_id=ws.id, title="남의 할 일")
    db_session.add(task)
    db_session.commit()

    resp = client.patch(
        f"/workspaces/{ws.id}/tasks/{task.id}", json={"status": "done"}
    )
    assert resp.status_code == 403


def test_list_tasks_requires_membership(client, db_session, test_user):
    from contest_helper_core.models import User, Workspace, WorkspaceMember

    # 남의 워크스페이스(현재 유저는 멤버 아님).
    other = User(
        email="boss@contest-helper.dev", name="사장", interests=[], skills=[]
    )
    db_session.add(other)
    db_session.commit()
    ws = Workspace(name="외부팀", owner_id=other.id)
    db_session.add(ws)
    db_session.commit()
    db_session.add(
        WorkspaceMember(workspace_id=ws.id, user_id=other.id, role="owner")
    )
    db_session.commit()

    assert client.get(f"/workspaces/{ws.id}/tasks").status_code == 403
