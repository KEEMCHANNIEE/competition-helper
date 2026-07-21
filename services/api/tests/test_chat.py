from app.chat.queue import CHAT_QUEUE_KEY


def test_post_chat_creates_conversation_and_enqueues(client, fake_redis):
    resp = client.post("/chat", json={"message": "안녕 에이전트"})
    assert resp.status_code == 202
    body = resp.json()
    conversation_id = body["conversation_id"]
    job_id = body["job_id"]
    assert conversation_id
    assert job_id

    # 채팅 큐 계약: 키와 페이로드가 정확히 들어갔는지.
    queued = fake_redis.lists[CHAT_QUEUE_KEY]
    assert len(queued) == 1
    assert job_id in queued[0]
    assert f'"conversation_id":{conversation_id}'.replace(" ", "") in queued[
        0
    ].replace(" ", "")


def test_post_chat_continues_existing_conversation(client, fake_redis):
    first = client.post("/chat", json={"message": "첫 메시지"}).json()
    conv_id = first["conversation_id"]

    second = client.post(
        "/chat", json={"conversation_id": conv_id, "message": "두번째"}
    ).json()
    assert second["conversation_id"] == conv_id

    # 두 메시지가 모두 같은 대화에 쌓인다.
    state = client.get(f"/chat/{conv_id}").json()
    assert [m["content"] for m in state["messages"]] == ["첫 메시지", "두번째"]


def test_get_chat_pending_when_no_assistant_reply(client):
    conv_id = client.post("/chat", json={"message": "응답 기다리는중"}).json()[
        "conversation_id"
    ]
    state = client.get(f"/chat/{conv_id}")
    assert state.status_code == 200
    body = state.json()
    assert body["conversation_id"] == conv_id
    assert body["pending"] is True
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"


def test_get_chat_not_pending_after_assistant_reply(client, db_session):
    from contest_helper_core.models import Message

    conv_id = client.post("/chat", json={"message": "질문"}).json()[
        "conversation_id"
    ]
    db_session.add(
        Message(conversation_id=conv_id, role="assistant", content="답변")
    )
    db_session.commit()

    body = client.get(f"/chat/{conv_id}").json()
    assert body["pending"] is False
    assert body["messages"][-1]["role"] == "assistant"


def test_get_chat_still_pending_when_internal_role_is_last(client, db_session):
    """recommend 같은 내부 기록이 assistant 답변보다 먼저 저장돼도 pending 이 유지된다."""
    from contest_helper_core.models import Message

    conv_id = client.post("/chat", json={"message": "공모전 추천해줘"}).json()[
        "conversation_id"
    ]
    db_session.add(
        Message(conversation_id=conv_id, role="recommend", content="[]")
    )
    db_session.commit()

    body = client.get(f"/chat/{conv_id}").json()
    assert body["pending"] is True  # 아직 assistant 답변이 없다

    db_session.add(Message(conversation_id=conv_id, role="assistant", content="답변"))
    db_session.commit()
    assert client.get(f"/chat/{conv_id}").json()["pending"] is False


def test_get_chat_missing_conversation_404(client):
    assert client.get("/chat/9999").status_code == 404


def test_post_chat_to_foreign_conversation_404(client, db_session):
    from contest_helper_core.models import Conversation, User

    other = User(
        email="stranger@contest-helper.dev", name="남", interests=[], skills=[]
    )
    db_session.add(other)
    db_session.commit()
    conv = Conversation(user_id=other.id, workspace_id=None)
    db_session.add(conv)
    db_session.commit()

    resp = client.post(
        "/chat", json={"conversation_id": conv.id, "message": "침입"}
    )
    assert resp.status_code == 404
