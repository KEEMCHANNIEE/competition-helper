"""자유 질문(개념 설명/비교/팀 적합도 등)에 답하는 도구 호출 오케스트레이션.

``agent.chat()`` 이 study 폴백일 때 이 모듈의 ``_handle_study()`` 를 직접 호출한다.
plan/recommend/progress 등 다른 인텐트 어디에도 안 걸리는 나머지 질문은 전부 여기로 온다.

인텐트를 미리 키워드/LLM으로 하나씩 분류해서 if/elif로 라우팅하는 대신,
LLM에 파이썬 함수를 도구로 직접 넘긴다(``LLMClient.generate_with_tools``,
google-genai의 Automatic Function Calling). 모델이 필요하다고 판단하면
SDK가 그 함수를 직접 실행하고 결과를 다시 모델에 먹여 최종 답을 만든다.
"어떤 질문에 어떤 도구를 쓸지"는 각 도구 함수의 docstring이 기준이 된다 —
새 도구를 추가할 때 agent.py의 인텐트 분기를 늘릴 필요가 없다.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from contest_helper_core.db import get_engine
from contest_helper_core.models import Conversation, Message, Recommendation
from contest_helper_core.schemas import MessageOut
from worker.llm import GeminiClient, LLMClient
from worker.search_filters import extract_keyword_and_filters
from worker.style import STYLE_GUIDE
from worker.team_fit import evaluate_team_fit


def _handle_study(
    last_user_msg: str,
    history: list[MessageOut],
    conversation_id: int,
    tools: dict,
    *,
    llm: LLMClient | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    """도구 사용이 필요할 수 있는 자유 질문에 답한다.

    Args:
        last_user_msg: 사용자의 마지막 메시지.
        history: 대화 기록(도구가 판단할 맥락 — 예: 직전 추천에서 언급된 공모전 id).
        conversation_id: 이 대화의 워크스페이스를 찾기 위한 id(팀 적합도 도구용).
        tools: mcp 도구 레지스트리.
        llm: LLM 클라이언트(미지정 시 GeminiClient). 테스트는 가짜 주입.
        session_factory: 세션 팩토리(미지정 시 App DB). 테스트는 SQLite 팩토리 주입.

    Returns:
        어시스턴트 답변 텍스트.
    """
    if not last_user_msg:
        return "무엇을 도와드릴까요? '추천해줘' / '계획 짜줘' 처럼 말씀해 주세요."

    if session_factory is None:
        session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    workspace_id = _load_workspace_id(conversation_id, session_factory)

    callables: list[Callable] = [
        _make_compare_tool(tools),
        _make_get_competition_detail_tool(tools),
        _make_search_tool(conversation_id, history, tools, session_factory),
        _make_web_search_tool(tools),
    ]
    if workspace_id is not None:
        callables.append(_make_team_fit_tool(workspace_id, tools, session_factory))
        callables.append(_make_list_saved_tool(workspace_id, session_factory))

    # 직전 추천/검색 목록의 순번↔id 매핑을 명시로 준다. 대화 기록 속 JSON(role=recommend)을
    # LLM이 스스로 파싱하게 두면 "첫 번째 거 자세히" 같은 요청이 가끔 엉뚱한 id로 풀린다.
    latest = load_latest_recommend_list(conversation_id, session_factory=session_factory)
    recommend_block = ""
    if latest:
        listing = "\n".join(f"{e['ordinal']}. {e['title']} (id={e['id']})" for e in latest)
        recommend_block = f"""

[직전 추천/검색 목록 — 순번 ↔ 내부 id]
{listing}
사용자가 "첫 번째/1번"처럼 순번으로 가리키면 위 목록의 그 순번 항목을 뜻합니다.
도구를 호출할 때는 반드시 이 id를 쓰고, id 는 어떤 형태로도 사용자에게 노출하지 마세요."""

    history_text = "\n".join(f"{m.role}: {m.content}" for m in history)
    prompt = f"""당신은 공모전 준비를 돕는 도우미입니다.

[도구 사용 규칙 — 반드시 지키세요]
1. 사실 확인·비교·재검색이 필요한 질문이면, 답을 짐작하지 말고 **그 즉시 해당
   도구를 실제로 호출**한 뒤 결과를 바탕으로 답하세요. 특히 "작년/역대 수상작",
   "심사위원", "최근 소식" 등 공모전 DB에 없는 사실을 묻는 질문은 예외 없이
   web_search 도구를 먼저 호출해야 합니다. 스스로 안다고 생각해도 확인 없이
   답하지 마세요.
2. 도구를 실제로 호출하지 않은 채로 "검색할 수 없다", "인터넷에 접속할 수
   없다", "기술적 오류가 발생했다", "정보를 찾지 못했다" 같은 말을 하는 것은
   금지됩니다. 이런 말은 도구를 실제로 호출해서 결과를 받아본 뒤, 그 결과가
   부족할 때만 사실대로 쓸 수 있습니다.
3. 개념 설명처럼 도구 없이도 확실히 답할 수 있는 질문은 그냥 답하세요.

{STYLE_GUIDE}
{recommend_block}

[대화 기록]
{history_text}

사용자의 마지막 질문: {last_user_msg}"""

    client = llm or GeminiClient()
    return client.generate_with_tools(prompt, tools=callables)


def _make_compare_tool(tools: dict) -> Callable:
    def compare_competitions(competition_ids: list[int]) -> str:
        """대화 기록에 남아있는 추천/검색 결과에서 공모전 id들을 찾아 비교한다.

        사용자가 방금 언급된 공모전들을 비교해달라고 할 때 이 함수를 호출하세요.
        id는 대화 기록 속 추천/검색 결과 기록에서 찾을 수 있습니다.

        Args:
            competition_ids: 비교할 공모전 id 목록(2개 이상).
        """
        details = tools["compare_competitions"](competition_ids)
        if len(details) < 2:
            return "비교할 공모전 정보를 충분히 찾지 못했어요."
        return _format_comparison(details)

    return compare_competitions


def _make_get_competition_detail_tool(tools: dict) -> Callable:
    def get_competition_detail(competition_id: int) -> str:
        """공모전 하나의 상세 정보(참가자격/제출요건/팀구성/심사기준/마감 등)를 조회한다.

        "이거 혼자도 나갈 수 있어?", "분량이 얼마나 돼?", "심사 기준이 뭐야?",
        "준비 기간이 얼마나 걸릴까?"처럼 특정 공모전의 사실을 물을 때 호출하세요.
        id는 대화 기록 속 추천/검색 결과 기록에서 찾을 수 있습니다.

        Args:
            competition_id: 조회할 공모전 id.
        """
        detail = tools["get_competition_detail"](competition_id)
        if detail is None:
            return "해당 공모전 정보를 찾지 못했어요."
        return _format_detail(detail)

    return get_competition_detail


def _make_search_tool(
    conversation_id: int,
    history: list[MessageOut],
    tools: dict,
    session_factory: Callable[[], Session] | None,
) -> Callable:
    def search_competitions(keyword: str | None = None) -> str:
        """조건을 바꿔 공모전을 다시 검색한다.

        "마감 촉박한데 다른 거 없어?", "상금 더 큰 거 없어?", "비슷한 다른 공모전도
        보여줘"처럼 재검색을 요청할 때 호출하세요. 결과는 순번으로만 보여주고
        내부 고유번호는 사용자에게 노출하지 마세요.

        Args:
            keyword: 검색 키워드(분야/주제 등). 없으면 비워도 됩니다.
        """
        # 대화에서 파악된 구조화 조건(마감·상금·대상 등)을 함께 적용한다 —
        # 키워드만으로 재검색하면 사용자가 앞서 말한 조건이 증발한다.
        user_msgs = [m.content for m in history if m.role == "user"]
        extracted_kw, filters = extract_keyword_and_filters(user_msgs)
        results = tools["search_competitions"](
            keyword=keyword or extracted_kw, filters=filters, limit=5
        )
        if not results:
            # 필터가 과하게 걸러냈을 수 있으니 키워드만으로 한 번 더 시도한다.
            results = tools["search_competitions"](keyword=keyword, limit=5)
        if not results:
            return "조건에 맞는 공모전을 찾지 못했어요."
        entries = save_recommend_list(conversation_id, results, session_factory=session_factory)
        lines = [
            f"{e['ordinal']}. {c.title} (마감 {c.deadline})" for e, c in zip(entries, results)
        ]
        return "\n".join(lines)

    return search_competitions


def _make_web_search_tool(tools: dict) -> Callable:
    def web_search(query: str) -> str:
        """DB에 없는 정보(작년 수상작, 심사위원 등)를 인터넷에서 찾아본다.

        공모전 DB에 없는 사실을 물어볼 때(예: "작년 수상작 뭐였어?", "심사위원
        누구야?") 호출하세요. 결과가 없을 수 있으니, 못 찾았으면 지어내지 말고
        솔직하게 "정보를 찾지 못했다"고 답하세요.

        Args:
            query: 검색어.
        """
        results = tools["web_search"](query, max_results=3)
        if not results:
            return "관련 정보를 웹에서 찾지 못했어요."
        lines = [f"- {r.title}\n  {r.snippet}\n  출처: {r.url}" for r in results]
        return "\n".join(lines)

    return web_search


def save_recommend_list(
    conversation_id: int,
    competitions: list,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> list[dict]:
    """추천/검색 결과를 ``Message(role="recommend")`` 로 저장하고 순번 매긴 목록을 반환한다.

    사용자에게는 이 순번만 보여주고(예: "1. OO공모전"), 진짜 DB id는 이 메시지
    안에만 남긴다. LLM은 대화 기록을 통해 이 id를 읽어 ``compare_competitions``/
    ``get_competition_detail`` 같은 도구를 호출할 때 쓴다.

    Args:
        conversation_id: 결과를 저장할 대화 id.
        competitions: ``id``/``title`` 속성을 가진 공모전 객체 목록(순서 = 순번).
        session_factory: 세션 팩토리(미지정 시 App DB). 테스트는 SQLite 팩토리 주입.

    Returns:
        ``[{"ordinal": 1, "id": 12, "title": "..."}, ...]`` 형태의 목록.
        객체에 마감·카테고리·상금 정보가 있으면 함께 저장한다 — 프론트가 이 기록을
        읽어 추천 카드를 그린다(답변 텍스트에는 상세를 반복하지 않는 분업).
    """
    if session_factory is None:
        session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)

    entries = []
    for i, c in enumerate(competitions):
        entry: dict = {"ordinal": i + 1, "id": c.id, "title": c.title}
        deadline = getattr(c, "deadline", None)
        if deadline is not None:
            entry["deadline"] = str(deadline)
        category = getattr(c, "category", None)
        if category:
            entry["category"] = list(category)[:3]
        prize = getattr(c, "first_prize_amount", None)
        if prize:
            entry["first_prize_amount"] = prize
        team = getattr(c, "team_config", None)
        if team:
            entry["team_config"] = team
        entries.append(entry)
    with session_factory() as session:
        session.add(
            Message(
                conversation_id=conversation_id,
                role="recommend",
                content=json.dumps(entries, ensure_ascii=False),
            )
        )
        session.commit()
    return entries


def load_latest_recommend_list(
    conversation_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> list[dict]:
    """이 대화에서 가장 최근에 저장된 추천/검색 결과 목록을 읽는다.

    ``save_recommend_list`` 가 저장한 형식(``[{"ordinal", "id", "title"}, ...]``)을
    그대로 반환한다. 저장된 게 없으면 빈 리스트.
    """
    if session_factory is None:
        session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)

    with session_factory() as session:
        row = (
            session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id, Message.role == "recommend")
                .order_by(Message.id.desc())
            )
            .scalars()
            .first()
        )
    if row is None:
        return []
    try:
        return json.loads(row.content)
    except (json.JSONDecodeError, TypeError):
        return []


def _make_team_fit_tool(
    workspace_id: int,
    tools: dict,
    session_factory: Callable[[], Session] | None,
) -> Callable:
    def check_team_fit() -> str:
        """지금 워크스페이스 팀원들이 이 공모전에 얼마나 잘 맞는지 평가한다.

        사용자가 "우리 팀이 잘할 수 있을까?", "팀 적합도 어때?" 등을 물으면
        이 함수를 호출하세요. 인자는 필요 없습니다.
        """
        return evaluate_team_fit(workspace_id, session_factory=session_factory, tools=tools)

    return check_team_fit


def _make_list_saved_tool(
    workspace_id: int,
    session_factory: Callable[[], Session] | None,
) -> Callable:
    def list_saved_competitions() -> str:
        """지금 워크스페이스에 팀원들이 저장해 둔 공모전 목록을 조회한다.

        "워크스페이스에 등록된 공모전이 뭐야", "우리 팀이 저장한 공모전 보여줘"처럼
        팀 전체가 공유하는 저장 목록을 물을 때 이 함수를 호출하세요. 대화창에서
        방금 검색/추천한 결과와는 다른, 워크스페이스에 실제로 저장된 목록입니다.
        인자는 필요 없습니다.
        """
        factory = session_factory or sessionmaker(bind=get_engine(), expire_on_commit=False)
        with factory() as session:
            rows = list(
                session.scalars(
                    select(Recommendation)
                    .where(Recommendation.workspace_id == workspace_id)
                    .order_by(Recommendation.id.asc())
                )
            )
        if not rows:
            return "아직 이 워크스페이스에 저장된 공모전이 없어요."
        return "\n".join(f"- {r.title} (저장 이유: {r.reason})" for r in rows)

    return list_saved_competitions


def _format_comparison(details: list) -> str:
    lines = ["공모전을 비교해봤어요:", ""]
    for d in details:
        prize = f"{d.total_prize_amount:,}원" if d.total_prize_amount else "정보 없음"
        deadline = d.deadline.isoformat() if d.deadline else "정보 없음"
        category = ", ".join(d.category) if d.category else "정보 없음"
        criteria = ", ".join(d.evaluation_criteria) if d.evaluation_criteria else "정보 없음"
        lines.append(f"- {d.title}")
        lines.append(f"  마감: {deadline} / 총상금: {prize}")
        lines.append(f"  참가유형: {d.participation_type or '정보 없음'} / 카테고리: {category}")
        lines.append(f"  심사기준: {criteria}")
    return "\n".join(lines)


def _format_detail(d) -> str:
    prize = f"{d.total_prize_amount:,}원" if d.total_prize_amount else "정보 없음"
    deadline = d.deadline.isoformat() if d.deadline else "정보 없음"
    participation = d.participation_type or "정보 없음"
    team = d.team_config or "정보 없음"
    requirements = ", ".join(d.requirements) if d.requirements else "정보 없음"
    criteria = ", ".join(d.evaluation_criteria) if d.evaluation_criteria else "정보 없음"
    return (
        f"{d.title}\n"
        f"마감: {deadline} / 총상금: {prize}\n"
        f"참가유형: {participation} / 팀구성: {team}\n"
        f"지원자격: {requirements}\n"
        f"심사기준: {criteria}"
    )


def _load_workspace_id(conversation_id: int, session_factory: Callable[[], Session]) -> int | None:
    with session_factory() as session:
        conv = session.get(Conversation, conversation_id)
        return conv.workspace_id if conv else None
