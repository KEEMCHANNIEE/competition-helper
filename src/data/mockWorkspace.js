export const workspace = {
  contest: {
    id: "contest_2026_012",
    title: "제4회 2026년 직지콘텐츠 공모전",
    host: "청주고인쇄박물관",
    category: ["사진/영상", "문학"],
    target: "대상 제한 없음 (대학생 및 전 국민)",
    start_date: "2026-07-01",
    end_date: "2026-07-26",
    submission_method: "직지콘텐츠 공모전 홈페이지(jikji.gcontest.co.kr) 가입 후 온라인 접수",
    requirements: [
      "시: A4용지 가로세로 여백 26mm, 줄간격 160%, 함초롱바탕체 (PDF 파일 제출)",
      "수필: 200자 원고지 12~14매 분량 (PDF 파일 제출)",
      "홍보영상: 1분 30초 ~ 3분 이내, 1920×1080(HD) 이상, 용량 50MB 이하",
      "인스타툰: 20컷 이내, 가로×세로 1080px, 300dpi 이상 (PDF 파일 제출)",
    ],
    evaluation_criteria: [
      { item: "주제성", score: 50, point: "직지 또는 청주 소재와의 연관성 및 목적 부합도" },
      { item: "표현 및 구성", score: 30, point: "시/수필의 문장력 또는 영상의 편집 퀄리티" },
      { item: "독창성", score: 20, point: "기존에 없던 창의적이고 신선한 접근 방식인가" },
    ],
    keywords: ["직지", "청주", "콘텐츠", "영상", "시", "인스타툰"],
    description: JSON.stringify({
      summary: {
        catchphrase: "제4회 2026 직지콘텐츠 공모전",
        target_detail: "대한민국 국민 누구나 참가 가능하며, 개인 또는 팀으로 출품 가능합니다.",
      },
      content: {
        topic: "직지(세계 최초 금속활자본)와 청주를 소재로 한 창작물",
        requirements: [
          "시: A4용지 가로세로 여백 26mm, 줄간격 160%, 함초롱바탕체 (PDF 파일 제출)",
          "수필: 200자 원고지 12~14매 분량 (PDF 파일 제출)",
          "홍보영상: 1분 30초 ~ 3분 이내, 1920×1080(HD) 이상, 용량 50MB 이하",
          "인스타툰: 20컷 이내, 가로×세로 1080px, 300dpi 이상",
        ],
        evaluation_criteria: [
          "주제성 (50점): 직지/청주 소재와의 연관성",
          "표현 및 구성 (30점): 문장력 또는 편집 퀄리티",
          "독창성 (20점): 창의적이고 신선한 접근 방식",
        ],
        submission_method: "직지콘텐츠 공모전 홈페이지(jikji.gcontest.co.kr) 가입 후 온라인 접수",
      },
      participation: {
        team_config: "개인 또는 팀 (공동출품 시 대표자 명기)",
        participation_type: "individual_or_team",
      },
      benefits: {
        prizes: ["대상 300만원", "최우수상 200만원", "우수상 100만원", "장려상 50만원"],
        extra_benefits: ["수상작 전시 기회 제공"],
        is_career_benefit: false,
      },
      schedule: {
        result_announcement: { date: "2026-08-25", note: "홈페이지 공지 예정" },
        award_ceremony: { date: null, note: "추후 공지" },
      },
      keywords: ["직지", "청주", "콘텐츠", "영상", "시", "인스타툰"],
      optional: {
        faq: "Q. 중복 출품 가능한가요? A. 동일 작품의 중복 출품은 불가합니다.",
        notes: "수상작의 저작권은 주최측에 귀속될 수 있으며, 타 공모전 수상작은 제출 불가합니다.",
      },
    }),
  },

  tasks: [
    { id: 1, title: "공모전 공고 분석", assignee: "김철수", priority: "High", dueDate: "2026-07-05", completed: true },
    { id: 2, title: "아이디어 회의", assignee: "박영희", priority: "High", dueDate: "2026-07-08", completed: true },
    { id: 3, title: "스토리보드 작성", assignee: "이민수", priority: "Medium", dueDate: "2026-07-12", completed: false },
    { id: 4, title: "영상 촬영", assignee: "김철수", priority: "Medium", dueDate: "2026-07-15", completed: false },
    { id: 5, title: "영상 편집", assignee: "이민수", priority: "High", dueDate: "2026-07-20", completed: false },
    { id: 6, title: "최종 검토", assignee: "박영희", priority: "High", dueDate: "2026-07-24", completed: false },
    { id: 7, title: "최종 제출", assignee: "박영희", priority: "High", dueDate: "2026-07-25", completed: false },
  ],

  schedules: [
    { id: 1, title: "Kick-off Meeting", date: "2026-07-02", type: "team" },
    { id: 2, title: "아이디어 확정", date: "2026-07-08", type: "team" },
    { id: 3, title: "스토리보드 리뷰", date: "2026-07-12", type: "team" },
    { id: 4, title: "영상 촬영", date: "2026-07-15", type: "team" },
    { id: 5, title: "최종 점검", date: "2026-07-23", type: "team" },
    { id: 6, title: "공모전 제출", date: "2026-07-26", type: "contest" },
    { id: 7, title: "접수 시작 (공식)", date: "2026-07-01", type: "contest" },
    { id: 8, title: "접수 마감 (공식)", date: "2026-07-26", type: "contest" },
    { id: 9, title: "결과 발표 (공식)", date: "2026-08-25", type: "contest" },
  ],

  meetings: [
    {
      id: 1,
      title: "Kick-off Meeting",
      date: "2026-07-02",
      summary: "공모전 분석 및 역할 분담. 영상 부문으로 출품 방향 결정. 김철수(촬영), 박영희(기획/제출), 이민수(편집) 담당 확정.",
      content: "공모전 분석 및 역할 분담을 진행했습니다.\n\n**결정 사항**\n- 영상 부문으로 출품 방향 결정\n- 김철수: 촬영 담당\n- 박영희: 기획 및 최종 제출 담당\n- 이민수: 편집 담당\n\n**다음 일정**\n- 7월 8일: 아이디어 확정 회의\n- 각자 레퍼런스 자료 3개 이상 준비",
    },
    {
      id: 2,
      title: "아이디어 회의",
      date: "2026-07-08",
      summary: "직지 금속활자 제작 과정을 현대적 시각으로 재해석하는 영상 콘셉트 확정. 브이로그 형식 + 인터뷰 혼합 방식 채택.",
      content: "영상 콘셉트를 확정했습니다.\n\n**콘셉트**\n직지 금속활자 제작 과정을 현대적 시각으로 재해석\n\n**형식**\n- 브이로그 형식 + 인터뷰 혼합 방식\n- 청주 현지 촬영 포함\n- 배경음악: 전통 국악 + 현대 음악 믹스\n\n**다음 일정**\n- 7월 12일: 스토리보드 리뷰\n- 이민수: 스토리보드 초안 작성",
    },
    {
      id: 3,
      title: "스토리보드 리뷰",
      date: "2026-07-12",
      summary: "이민수 스토리보드 공유. 오프닝 씬 수정 필요. 인터뷰 대상 섭외 시작. 다음 회의 전까지 수정본 제출.",
      content: "이민수가 작성한 스토리보드를 리뷰했습니다.\n\n**피드백**\n- 오프닝 씬: 직지 이미지를 먼저 보여주는 방식으로 수정 필요\n- 인터뷰 씬: 자막 추가 필요\n- 전체 러닝타임: 현재 3분 20초 → 3분 이내로 편집 필요\n\n**액션 아이템**\n- 이민수: 수정본 7월 14일까지 제출\n- 박영희: 인터뷰 대상 섭외 시작\n- 김철수: 촬영 장비 점검",
    },
  ],

  insights: [
    {
      id: 1,
      title: "직지 콘텐츠 조사",
      author: "박영희",
      createdAt: "2026-07-03",
      preview: "직지는 세계 최초의 금속활자본으로 1377년 청주 흥덕사에서 제작되었다. 유네스코 세계기록유산으로 등재되어 있으며...",
      content: "# 직지 콘텐츠 조사\n\n## 직지란?\n직지심체요절(直指心體要節)은 세계 최초의 금속활자본으로, 1377년 청주 흥덕사에서 제작되었습니다.\n\n## 주요 특징\n- 유네스코 세계기록유산 등재 (2001년)\n- 구텐베르크 성경보다 78년 앞서 제작\n- 현재 프랑스 국립도서관 소장\n\n## 공모전 활용 포인트\n- 직지의 역사적 가치를 현대적으로 재해석\n- 청주와 직지의 연관성 강조\n- 금속활자 제작 과정 시각화",
    },
    {
      id: 2,
      title: "영상 제작 참고 자료",
      author: "이민수",
      createdAt: "2026-07-10",
      preview: "공모전 영상 심사 기준 분석 결과, 브이로그 형식이 주제 전달력과 편집 퀄리티 측면에서 가장 유리할 것으로 판단...",
      content: "# 영상 제작 참고 자료\n\n## 심사 기준 분석\n주제성(50점)이 가장 높으므로 직지/청주 소재를 명확히 드러내는 것이 핵심입니다.\n\n## 형식 선택\n브이로그 형식이 가장 유리한 이유:\n- 자연스러운 스토리텔링 가능\n- 현장감 전달에 효과적\n- 편집 난이도 적절\n\n## 기술 스펙\n- 해상도: 1920×1080 이상\n- 러닝타임: 1분 30초 ~ 3분\n- 용량: 50MB 이하",
    },
    {
      id: 3,
      title: "평가기준 분석",
      author: "김철수",
      createdAt: "2026-07-11",
      preview: "주제성 50점 배점으로 가장 높음. 직지와 청주를 소재로 한 콘텐츠임을 명확히 드러내는 것이 핵심...",
      content: "# 평가기준 분석\n\n## 배점 구조\n- 주제성: 50점 (가장 중요)\n- 표현 및 구성: 30점\n- 독창성: 20점\n\n## 전략\n주제성 50점 확보를 위해 영상 전반에 걸쳐 직지와 청주를 명확히 드러내야 합니다.\n\n## 체크리스트\n- [ ] 직지 언급 최소 3회 이상\n- [ ] 청주 현지 촬영 포함\n- [ ] 금속활자 제작 과정 시각화\n- [ ] 역사적 의미 자막 추가",
    },
  ],
};
