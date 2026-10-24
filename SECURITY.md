# 보안 범위와 취약점 보고

현재 지원 대상은 신뢰할 수 있는 한 사용자의 로컬 실행입니다. Backend와 Frontend를 `127.0.0.1`에 바인딩하고 인터넷이나 신뢰하지 않는 LAN에 직접 노출하지 않습니다. 인증·사용자별 데이터 격리·업로드 용량 제한·rate limit은 아직 제공하지 않습니다.

원문, 기준 음성, 전사와 생성물은 기본적으로 `backend/storage/`에 저장됩니다. JSON 백업과 ZIP에도 원문과 음성 관련 metadata가 들어갑니다. 외부 AI provider를 선택하면 생성할 자료가 해당 provider로 전달됩니다. cookie와 CLI 로그인 파일은 공개 저장소나 bug report에 포함하지 않습니다.

텍스트 AI는 기본 로컬 전용이며 외부 provider 사용은 명시적으로 선택합니다. NVIDIA/custom API key는 Backend의 `ai_text_connections.json`에 permission 0600으로 저장하고 공개 API에는 존재 여부만 반환합니다. 이 파일은 평문이므로 로컬 OS 계정과 디스크 보안에 의존하며 공개 저장소·백업 공유·bug report에 포함하지 않습니다.

파일 읽기 경계 우회, media URL 검증 우회, 사적 원문·자산 노출이나 외부 AI 호출 경계 문제가 발견되면 공개 issue에 exploit과 실제 음성을 올리지 말고 저장소의 GitHub Security 탭에서 `Report a vulnerability`가 활성화되어 있는지 확인해 비공개로 보고해 주세요. 활성화되어 있지 않으면 재현 자료를 게시하지 말고 먼저 관리자에게 비공개 보고 채널 제공을 요청하세요.

보고에는 영향, 재현 가능한 최소 입력, OS와 관련 파일·API 경로를 포함합니다. 위 공개 SaaS 미구현 사항은 현재 제품 경계이며, 인터넷 서비스를 구성하려면 별도 설계와 검증이 필요합니다.
