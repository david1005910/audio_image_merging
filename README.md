# WaveStudio Pro (audio_image_merging)

> 오디오와 이미지를 합성하여 1080p 고화질 비디오를 생성하는 풀스택 웹 스튜디오 및 Python/FFmpeg 미디어 엔진입니다.

---

## 🎬 주요 3대 스튜디오 모드

### 1. 🎞️ Remotion 스타일 멀티트랙 타임라인 스튜디오 (Timeline Editor)
- **3대 트랙 지원**: 미디어(이미지/영상) 트랙, 오디오(나레이션/BGM) 트랙, 자막(텍스트) 트랙
- **인터랙티브 타임라인 조작**: 마우스 드래그로 클립 이동, 양끝 엣지 핸들 드래그로 재생 시간(Duration) 조절
- **편집 도구**: 재생헤드 위치 기준 클립 분할(Split), 클립 삭제, 룰러 스크러빙
- **실시간 1080p 캔버스 & Web Audio 프리뷰**: 16:9 캔버스로 비주얼 및 자막 실시간 렌더링, 오디오 동기화 재생 (스페이스바 재생/일시정지)
- **클립 인스펙터 (Inspector)**: 시작 시간, 지속 시간, 자막 글꼴 크기/색상/배경(박스 vs 그림자)/위치(상단/중앙/하단), 오디오 볼륨(0~200%) 조절
- **1080p FFmpeg 타임라인 렌더링**: 비주얼 정규화/패딩, 클립 간 공백(Gap) 자동 블랙 프레임 처리, 오디오 딜레이/믹싱, libass 자막 번인

### 2. 📝 씬 & 나레이션 자막 스튜디오 (Multi-Scene Subtitles)
- 나레이션 대본 텍스트(.txt, .srt) 업로드 및 마침표/줄바꿈 기준 자동 문장 분할
- 여러 장의 이미지/동영상 씬에 자막을 균등 자동 배분
- 오디오 길이에 맞춘 씬 지속 시간 자동 균등 배분 (Auto-balance)
- 씬 순서 이동, 지속 시간 및 자막 내용 개별 커스텀 편집

### 3. ⚡ 클래식 비디오 모드 (Waveform & Overlay)
- **웨이브 오버레이 (Waveform Overlay)**: 배경 이미지 위에 반투명 오디오 파형 합성
- **파형 비디오 (Waveform Video)**: 오디오 신호 기반 단독 파형 시각화 비디오
- **정지 이미지 영상 (Static Video)**: 이미지 1장 + 오디오 결합 최적화 인코딩
- 네온 프리셋 팔레트, 파형 높이/투명도/위치 조절 및 All-in-One 일괄 렌더링

---

## 🚀 빠른 시작 (Quick Start)

### 사전 요구 사항
- **Python 3.9 이상**
- **FFmpeg**가 시스템 `PATH`에 등록되어 있어야 합니다.
- *외부 Python 패키지 설치(`pip install`) 불필요 (Python 표준 라이브러리 `http.server`, `subprocess`, `threading`, `json`만 사용)*

### Web UI 실행
```bash
python webui.py
```
기본 포트는 `8080`입니다. 포트 변경 시 인자로 지정할 수 있습니다:
```bash
python webui.py 8888
```
브라우저에서 **`http://127.0.0.1:8080`**으로 접속합니다.

---

## 🛠️ CLI 스크립트 실행 방법

개별 CLI 도구로도 실행 가능합니다:

```bash
# 1. Remotion 타임라인 렌더링 (Python 코드 또는 테스트 스크립트 참조)
python -c "import remotion_engine; ..."

# 2. 씬별 나레이션 자막 비디오 생성
python scene_video.py

# 3. 오디오 파형 오버레이 비디오
python waveform_overlay_video.py

# 4. 단독 오디오 파형 시각화
python waveform_video.py

# 5. 정지 이미지 + 오디오 비디오
python static_video.py

# 6. 폴더 일괄 변환 (Batch Convert)
python batch_convert.py --help
```

---

## 📁 프로젝트 구조

```
.
├── remotion_engine.py         # Remotion 멀티트랙 타임라인 FFmpeg 렌더링 엔진
├── scene_video.py             # 씬별 나레이션 자막 비디오 생성 엔진
├── waveform_overlay_video.py  # 배경 + 파형 오버레이 영상 생성
├── waveform_video.py          # 단독 오디오 파형 시각화 생성
├── static_video.py            # 정지 이미지 + 오디오 영상 생성
├── batch_convert.py           # CLI 디렉터리 일괄 변환 도구
├── webui.py                   # Fullstack HTTP 서버 & REST API 백엔드
├── templates/
│   └── index.html             # 시맨틱 스튜디오 HTML UI (Remotion / Scene / Classic)
├── static/
│   ├── css/
│   │   └── style.css          # 다크 글래스모피즘 디자인 시스템 & 타임라인 스타일
│   └── js/
│       ├── remotion_editor.js # Remotion 멀티트랙 타임라인 에디터 프론트엔드 엔진
│       ├── audio_preview.js   # Web Audio API 파형 시각화 및 오디오 플레이어
│       └── app.js             # 스튜디오 탭 상태 머신, API 폴링 & 보관함 매니저
├── uploads/                   # 작업별 업로드 임시 디렉터리
└── outputs/                   # 렌더링 완료된 1080p MP4 결과물 보관소
```

---

## 🔌 REST API 명세

| 메서드 | 엔드포인트 | 설명 |
|---|---|---|
| `GET` | `/` | 메인 스튜디오 웹 인터페이스 반환 |
| `POST` | `/api/run` | 비디오 생성 작업 제출 (`tasks`: `remotion_render`, `scene_render`, `waveform_overlay` 등) |
| `GET` | `/api/status?id=<id>` | 작업 진행률 (0~100%), 상태, 로그, 결과 파일 URL 반환 |
| `POST` | `/api/cancel?id=<id>` | 실행 중인 FFmpeg 작업 취소 및 프로세스 강제 종료 |
| `GET` | `/api/files` | 생성된 비디오 목록 및 메타데이터 반환 |
| `DELETE`| `/api/files/<name>` | `outputs/` 파일 삭제 |
| `GET` | `/download/<name>` | HTTP 206 Partial Content 비디오 스트리밍 및 다운로드 |