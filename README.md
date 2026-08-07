# Metaverse-Projects

팀 프로젝트 진행을 위한 Git

**Commit Messege Rule**

커밋 메시지 구조

제목(Subject): 변경 내용을 한 줄로 요약 (타입: 요약문)

본문(Body): 무엇을, 왜 바꿨는지 상세 설명 (선택 사항)

꼬리말(Footer): 관련 이슈 번호 등 기록 (선택 사항)

주요 커밋 타입 (Type)

feat: 새로운 기능 추가

fix: 버그 수정

docs: 문서 수정

style: 코드 포맷팅, 세미콜론 누락 등 (코드 변경 없음)

refactor: 코드 리팩토링 (기능 변경 없음)

test: 테스트 코드 추가 및 수정

chore: 빌드 업무 수정, 패키지 매니저 설정 등


작성 규칙
제목은 50자 이내로 짧게 씁니다.

제목 끝에 마침표를 쓰지 않습니다.

명령문(동사 원형)으로 시작합니다 (예: Add, Fix).

제목과 본문은 빈 줄로 구분합니다.

**이 프로젝트에 대한 RULESETS** (main 브랜치만 적용)

**Restrict deletions (삭제 제한)**

이 규칙은 우회 권한이 있는 사용자만 특정 브랜치 또는 태그를 삭제할 수 있도록 제한합니다. 

**Require a pull request before merging(병합 전 끌어오기 요청 필요)**
이 옵션을 선택할 경우 모든 커밋은 대상 브랜치가 아닌 브랜치에서 이루어지고, 병합되기 전에 Pull Request를 통해 제출되어야 합니다. 위에서 아래로 옵션들로 서술하겠습니다..

**Require approvals**

pull Request가 병합되기 전에 필요한 승인 리뷰 수를 설정할 수 있습니다. 
팀원 중 적어도 2명이 코드 리뷰에서 approve를 해야 병합할 수 있음을 의미합니다. 
이를 통해 코드의 신뢰도를 높일 수 있습니다. 

Require review from Code Owners

Code Owner(코드 소유자 정보)에게 승인을 받아야함을 의미합니다. 코드 소유자가 직접 검토하여 코드 품질과 일관성을 유지합니다.

**Require approval of the most recent reviewable push**

푸시한 사람 외의 누군가의 승인을 받아야 합니다. 
푸시한 사람이 아닌 다른 개발자가 코드를 검토하도록 강제하여 객관적인 리뷰를 보장합니다.

Allowed merge methods

Pull Request 시 Merge, Rebase, Squash 중 허용된 병합 방법들을 설정할 수 있습니다. 

**Block force pushes(강제 푸시 차단)**

사용자가 대상 분기 또는 태그에 강제로 푸시하는 것을 방지할 수 있습니다.
강제 커밋을 할 경우 특정 커밋이 삭제될 수도 있고,
병합 충돌 또는 손상된 끌어오기 요청으로 이어질 수 있습니다.
이러한 문제들을 막기 위해 이 규칙은 기본적으로 사용하도록 설정되어 있습니다. 

Require code scanning results(code scanning 병합 보호 설정)

특정 브랜치나 태그가 업데이트되기 전에 코드 스캔 도구가 검사 결과를 제공해야 한다는 조건을 설정하는 기능입니다.
이 규칙을 활성화하면, 코드 변경 사항에 대한 보안 및 품질 검사를 자동으로 수행할 수 있습니다.
