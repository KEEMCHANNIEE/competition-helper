"""keenee agent-worker.

비동기 LLM 에이전트 런타임. Redis 큐에서 추천 작업을 꺼내
에이전트를 돌리고 결과를 App DB 에 적재한다.

- 배관(큐 루프·작업 상태기계·DB 영속화)은 ``main`` 에 완전히 구현돼 있다.
- 에이전트 두뇌(추론/RAG/LLM/MCP 도구)는 과제(stub)로 비어 있다.
"""
