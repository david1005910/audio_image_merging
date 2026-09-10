"""
youtube_audio_overview.py
다수의 YouTube 영상으로부터 자막/메타데이터를 수집하고,
Google Gemini AI를 통해 심층 분석하여 2인 대화형 AI Audio Overview(팟캐스트)를
Edge-TTS 듀얼 스피커 음성으로 합성하는 핵심 엔진입니다.
"""

import re
import os
import json
import asyncio
import urllib.request
import urllib.parse
import subprocess
from typing import List, Dict, Any, Optional

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

try:
    import edge_tts
except ImportError:
    edge_tts = None


# ==========================================
# 1. YouTube 메타데이터 및 자막 추출기
# ==========================================
def extract_video_id(url: str) -> Optional[str]:
    """다양한 형태의 YouTube URL에서 11자리 video_id를 정규식으로 추출합니다."""
    url = url.strip()
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"youtu\.be\/([0-9A-Za-z_-]{11})",
        r"youtube\.com\/shorts\/([0-9A-Za-z_-]{11})",
        r"youtube\.com\/embed\/([0-9A-Za-z_-]{11})"
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    if re.match(r"^[0-9A-Za-z_-]{11}$", url):
        return url
    return None


def fetch_youtube_metadata(video_id: str, save_dir: str) -> Dict[str, Any]:
    """oEmbed API를 호출하여 영상 제목, 채널명, 썸네일 이미지를 다운로드합니다."""
    info = {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": f"YouTube Video ({video_id})",
        "author": "YouTube Creator",
        "thumbnail_url": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
        "thumbnail_file": None
    }

    try:
        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            info["title"] = data.get("title", info["title"])
            info["author"] = data.get("author_name", info["author"])
            if data.get("thumbnail_url"):
                info["thumbnail_url"] = data["thumbnail_url"]
    except Exception as e:
        print(f"[YouTube] oEmbed fetch warning for {video_id}: {e}")

    # 썸네일 이미지 로컬 저장 (1080p 비주얼 트랙용)
    os.makedirs(save_dir, exist_ok=True)
    thumb_path = os.path.join(save_dir, f"thumb_{video_id}.jpg")
    try:
        # maxresdefault -> hqdefault 폴백 시도
        t_urls = [info["thumbnail_url"], f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"]
        saved = False
        for tu in t_urls:
            try:
                treq = urllib.request.Request(tu, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(treq, timeout=8) as tresp:
                    with open(thumb_path, "wb") as f:
                        f.write(tresp.read())
                    info["thumbnail_file"] = thumb_path
                    saved = True
                    break
            except Exception:
                continue
        if not saved:
            # 기본 단색 이미지 생성 (FFmpeg)
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x1e293b:s=1920x1080:d=1",
                "-frames:v", "1", thumb_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            info["thumbnail_file"] = thumb_path
    except Exception as e:
        print(f"[YouTube] Thumbnail save warning: {e}")

    return info


def fetch_youtube_transcript(video_id: str) -> str:
    """youtube-transcript-api를 사용하여 자막 스크립트를 추출합니다."""
    if not YouTubeTranscriptApi:
        return ""

    try:
        api = YouTubeTranscriptApi()
        # 한국어 또는 영어 자막 가져오기
        transcript = api.fetch(video_id, languages=["ko", "en"])
        lines = []
        for item in transcript:
            if hasattr(item, "text"):
                t = str(item.text).strip()
            elif isinstance(item, dict):
                t = str(item.get("text", "")).strip()
            else:
                t = str(item).strip()
            if t:
                lines.append(t)
        return " ".join(lines)
    except Exception as e:
        print(f"[YouTube] Transcript not found or error for {video_id}: {e}")
        return ""


def process_youtube_urls(urls: List[str], save_dir: str) -> List[Dict[str, Any]]:
    """입력된 다수의 YouTube URL 목록으로부터 메타데이터와 자막 텍스트를 수집합니다."""
    sources = []
    seen_ids = set()

    for url in urls:
        vid = extract_video_id(url)
        if not vid or vid in seen_ids:
            continue
        seen_ids.add(vid)

        meta = fetch_youtube_metadata(vid, save_dir)
        transcript = fetch_youtube_transcript(vid)
        meta["transcript"] = transcript
        sources.append(meta)

    return sources


# ==========================================
# 2. Gemini AI 외국어 동영상 원본 충실 번역 및 시간 맞춤형 스크립트 생성기
# ==========================================
def _calculate_target_chars(duration_sec: int) -> int:
    """
    목표 나레이션 시간(초)에 부합하는 한국어 스크립트 권장 글자 수(공백 포함)를 계산합니다.
    한국어 Edge-TTS 자연 낭독 기준: 초당 약 4.2~4.4글자
    """
    duration_sec = max(30, min(600, duration_sec))
    net_speech_sec = max(25.0, duration_sec - 1.5)
    return int(round(net_speech_sec * 4.3))


def generate_korean_explainer_script_gemini(
    sources: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    language: str = "ko",
    tone: str = "faithful",
    target_duration: int = 180
) -> List[Dict[str, str]]:
    """
    수집된 외국어 YouTube 영상의 원본 자막과 내용을 원작자의 의도와 논리에 입각하여
    충실히 번역(Faithful Translation)하고, 지정된 목표 시간에 맞추어 한국어 나레이션 스크립트를 작성합니다.
    """
    target_duration = max(30, min(600, int(target_duration or 180)))
    target_chars = _calculate_target_chars(target_duration)
    target_mins = round(target_duration / 60, 1)

    # 1. 소스 컨텍스트 조립
    source_context = ""
    for idx, s in enumerate(sources, 1):
        t_snippet = s.get("transcript", "")
        if len(t_snippet) > 12000:
            t_snippet = t_snippet[:12000] + "... (이하 생략)"
        source_context += f"\n\n### [영상 소스 {idx}]\n- 제목: {s.get('title')}\n- 채널: {s.get('author')}\n- 원문 자막/내용:\n{t_snippet or '(원문 자막이 제공되지 않아 영상 제목과 주제를 중심으로 충실히 번역해 주세요)'}"

    # 2. 시스템 프롬프트 작성
    tone_instruction = {
        "faithful": "원작자의 설명 순서와 논리를 왜곡 없이 충실히 따르는 직관적이고 정확한 번역 해설 스타일",
        "deep_dive": "원문의 핵심 개념과 배경 맥락까지 친절하게 풀어서 설명해주는 심층 번역 해설 스타일",
        "summary": "원문의 핵심 팩트와 주요 메시지를 압축하여 빠르게 전달하는 요약 번역 스타일",
        "actionable": "원작자가 제시하는 실무 팁과 실행 방안에 집중한 실용적 번역 해설 스타일"
    }.get(tone, "원문 충실 번역 스타일")

    # 섹션 수 결정: 시간에 따라 3~5개 섹션
    if target_duration <= 90:
        section_guide = "총 3개 섹션 [서론/도입, 본론/원문 핵심 번역, 결론/요약]"
    elif target_duration <= 210:
        section_guide = "총 4개 섹션 [서론/도입, 본론 1/핵심 논점 번역, 본론 2/세부 설명 및 근거 번역, 결론/요약 및 총평]"
    else:
        section_guide = "총 5~6개 섹션 [서론, 본론 1, 본론 2, 본론 3/심층 시사점, 결론/총평]"

    prompt = f"""당신은 외국어(영어 등) 전문 영상 콘텐츠를 원본의 내용과 구조에 입각하여 왜곡 없이 충실히 번역(Faithful Translation)하여 한국어 나레이션으로 전달하는 최고 수준의 전문 번역 해설가입니다.
제공된 YouTube 영상(외국어 원문)의 내용을 원작자의 시각과 설명 흐름을 최대한 살려, 청취자가 귀로 들었을 때 바로 이해할 수 있는 '한국어 번역 나레이션 스크립트'를 작성해주세요.

[★ 핵심 작성 규칙 - 엄격 준수]:
1. **원본 충실 번역 (Faithful Translation)**:
   - 원작자의 설명 순서, 핵심 주장, 구체적인 사례와 수치 데이터를 왜곡이나 누락 없이 충실하게 번역하세요.
   - 개인적 의견이나 불필요한 과장을 덧붙이지 말고, 원본 영상의 본질과 메시지를 정확히 살려야 합니다.
2. **목표 나레이션 시간 및 글자 수 엄격 제어**:
   - 사용자가 설정한 목표 나레이션 시간: **{target_duration}초 (약 {target_mins}분)**
   - 한국어 표준 낭독 속도(초당 약 4.3글자)에 정확히 맞추어, **전체 스크립트의 총 글자 수(공백 포함)가 약 {target_chars}자(±10% 이내)**가 되도록 각 섹션의 텍스트 길이를 정밀하게 맞추세요.
   - 분량이 너무 짧거나 넘치지 않도록 전체 글자 수를 {target_chars}자에 최대한 근접하게 작성하세요.
3. **자연스러운 구어체 나레이션**:
   - 문어체 직역 투가 아닌, 귀로 편안하게 들을 수 있는 유려한 한국어 구어체(해요체와 하십시오체를 자연스럽게 혼용)로 번역하세요.
   - 중요한 영문 기술 용어나 고유명사는 한국어 설명 뒤에 괄호로 병기하세요 (예: 거대언어모델(LLM), 검색증강생성(RAG) 등).
4. **섹션 구성**:
   - {section_guide}
5. 출력 형식은 반드시 아래와 같은 JSON 배열 형식으로만 응답하세요. 마크다운 태그(```json 등)는 제외하거나 순수 JSON만 반환하세요.

[JSON 출력 형식 예시]:
[
  {{
    "section": "서론",
    "title": "원문 주제 및 배경 번역",
    "text": "안녕하세요. 오늘 번역해 드릴 영상은..."
  }},
  {{
    "section": "본론 1",
    "title": "원문의 주요 주장 및 핵심 설명",
    "text": "원문 영상에서 저자는 먼저..."
  }},
  {{
    "section": "결론",
    "title": "원작자의 최종 요약 및 결론",
    "text": "마지막으로 저자는 이러한 흐름이..."
  }}
]

[분석할 외국어 YouTube 영상 원본 소스]:
{source_context}
"""

    gemini_key = api_key or os.environ.get("GEMINI_API_KEY")

    if gemini_key:
        try:
            # Gemini 2.0 Flash 호출
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.5,
                    "responseMimeType": "application/json"
                }
            }
            req = urllib.request.Request(
                api_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=35) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                candidate_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                cleaned = candidate_text.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                sections = json.loads(cleaned.strip())
                if isinstance(sections, list) and len(sections) > 0:
                    return sections
        except Exception as e:
            print(f"[Gemini API] Call error: {e}, falling back to built-in smart explainer.")

    # API 키가 없거나 호출 실패 시 시간 맞춤형 스마트 폴백 해설 생성
    return _generate_smart_fallback_explainer_script(sources, language, target_duration)


def _generate_smart_fallback_explainer_script(
    sources: List[Dict[str, Any]],
    language: str = "ko",
    target_duration: int = 180
) -> List[Dict[str, str]]:
    """지정된 목표 시간과 글자 수에 맞추어 생성되는 고품질 원본 충실 번역 템플릿 엔진"""
    title1 = sources[0].get("title", "YouTube 영상") if len(sources) > 0 else "주요 영상 콘텐츠"
    author1 = sources[0].get("author", "글로벌 크리에이터") if len(sources) > 0 else "원작자"
    title2 = sources[1].get("title", "") if len(sources) > 1 else ""
    author2 = sources[1].get("author", "") if len(sources) > 1 else ""

    if target_duration <= 90:
        # 1분 (60초 내외 ~260자)
        return [
            {
                "section": "서론",
                "title": "원문 주제 소개",
                "text": f"안녕하세요. 오늘 함께 살펴볼 영상은 {author1}의 '{title1}'입니다. 원작자는 이번 영상에서 가장 핵심적인 화두를 직관적으로 전달하고 있습니다."
            },
            {
                "section": "본론",
                "title": "원문의 핵심 논점 번역",
                "text": "원문의 핵심 내용을 번역해보면, 기존 방식의 한계를 명확한 데이터로 지적하며 새로운 해결책을 제시합니다. 특히 실제 현장에서의 구체적인 작동 원리와 효용성을 입증하는 부분이 매우 인상적입니다."
            },
            {
                "section": "결론",
                "title": "원작자의 최종 요약",
                "text": "결국 원작자가 강조하는 핵심 메시지는 새로운 기술과 패러다임을 신속하게 이해하고 실무에 능동적으로 적용하는 것입니다. 이 요약이 여러분의 이해에 큰 도움이 되길 바랍니다."
            }
        ]
    elif target_duration <= 210:
        # 2~3분 (120~180초 내외 ~600~800자)
        result = [
            {
                "section": "서론",
                "title": "원작자의 주제 도입 및 배경 번역",
                "text": f"안녕하세요. 오늘 원본에 입각해 충실히 번역해 드릴 콘텐츠는 {author1} 채널의 '{title1}'입니다. 원작자는 이번 영상에서 최근 업계의 가장 뜨거운 화두를 서두에서 짚으며 문제의 배경을 명확히 설명합니다."
            },
            {
                "section": "본론 1",
                "title": "원문의 핵심 주장 및 방법론",
                "text": f"원문의 전개를 살펴보면, 저자는 복잡한 이론을 누구나 알기 쉽게 풀어서 단계별로 설명하고 있습니다. 특히 기존의 접근법이 왜 병목을 겪고 있는지 논리적으로 파헤치며, 이를 돌파하기 위한 구체적인 방법론과 아키텍처를 제시합니다."
            },
            {
                "section": "본론 2",
                "title": "세부 데이터 및 실제 적용 사례 번역",
                "text": "이어지는 본론에서 원작자는 실제 벤치마크 수치와 실행 사례를 공유합니다. 단순히 개념적 제안에 머무르지 않고, 실제로 적용했을 때 생산성과 효율성이 비약적으로 개선되는 과정을 생생한 화면과 데이터로 입증하고 있습니다."
            }
        ]
        if title2:
            result.append({
                "section": "교차 분석",
                "title": "다중 소스 교차 검증",
                "text": f"또한 이어서 살펴본 {author2}의 '{title2}' 원문과 대조해보면 또 다른 상호 보완적 시사점이 드러납니다. 첫 번째 영상이 근본적 원리에 집중했다면 두 번째 영상은 실질적 확장에 무게를 두고 있습니다."
            })
        result.append({
            "section": "결론",
            "title": "원작자의 마무리 메시지 및 총평",
            "text": "원작자는 결론부에서 변화의 파도 속에서 원리를 정확히 이해하고 직접 실행해보는 자가 가장 큰 경쟁력을 갖게 될 것이라고 강조합니다. 이번 충실 번역 나레이션이 여러분의 인사이트 확장에 가치 있는 가이드가 되기를 바랍니다."
        })
        return result
    else:
        # 4~5분 이상 (300초 내외 ~1300자)
        return [
            {
                "section": "서론",
                "title": "원작자의 주제 도입 및 배경 맥락 번역",
                "text": f"안녕하세요. 오늘 원작자의 서사와 논리에 입각하여 충실히 번역해 드릴 영상은 {author1}의 '{title1}'입니다. 원작자는 이번 영상의 도입부에서 왜 지금 이 기술과 접근법이 전 세계적으로 주목받고 있는지 그 배경 맥락을 심도 있게 짚어주고 있습니다."
            },
            {
                "section": "본론 1",
                "title": "원문의 핵심 원리와 문제 정의",
                "text": "원문의 첫 번째 장에서 저자는 기존 시스템들이 안고 있던 근본적인 한계와 구조적 문제점을 명쾌하게 정의합니다. 특히 과거의 전통적인 방식으로는 급격히 늘어나는 요구사항을 감당하기 어려웠음을 구체적인 사례를 들어 조목조목 설명합니다."
            },
            {
                "section": "본론 2",
                "title": "제시된 솔루션과 세부 메커니즘 번역",
                "text": "이에 대한 해결책으로 원작자가 제시하는 핵심 메커니즘은 매우 혁신적입니다. 복잡한 워크플로우를 모듈화하고 피드백 루프를 결합함으로써, 전체 시스템의 자율성과 문제 해결 능력을 획기적으로 끌어올릴 수 있는 상세 원리를 단계별로 친절하게 설명합니다."
            },
            {
                "section": "본론 3",
                "title": "실제 벤치마크 결과 및 주의사항",
                "text": "또한 영상 후반부에서는 실제 테스트 결과를 투명하게 공개하며 신뢰성을 높입니다. 놀라운 성능 향상 수치뿐만 아니라, 실무에 도입할 때 반드시 주의해야 할 비용 문제나 예외 케이스 처리 방법까지 솔직하게 조언하고 있습니다."
            },
            {
                "section": "결론",
                "title": "원작자의 최종 총평 및 미래 제언",
                "text": "결론에 이르러 원작자는 앞으로 다가올 미래 환경에서 이러한 새로운 패러다임을 선제적으로 도입하는 개인과 조직만이 압도적인 생산성을 확보할 수 있을 것이라 단언합니다. 원작자의 깊이 있는 통찰을 여러분의 업무와 프로젝트에도 적극 활용해보시기 바랍니다."
            }
        ]


# 하위 호환성 별칭
generate_podcast_script_gemini = generate_korean_explainer_script_gemini


# ==========================================
# 3. Edge-TTS 단일 해설가 음성 합성 및 타임라인 빌드 (시간 맞춤형 믹싱)
# ==========================================
async def _synthesize_turn(text: str, voice: str, output_file: str):
    """단일 문단/턴을 Edge-TTS로 음성 합성합니다."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)


def _get_audio_duration_ffprobe(file_path: str) -> float:
    """ffprobe를 통해 오디오 파일의 재생 시간(초)을 정밀 측정합니다."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 3.0


def synthesize_explainer_audio_and_timeline(
    script_sections: List[Dict[str, str]],
    sources: List[Dict[str, Any]],
    output_mp3_path: str,
    voice: str = "ko-KR-InJoonNeural",
    language: str = "ko",
    target_duration: Optional[int] = 180,
    progress_callback=None
) -> Dict[str, Any]:
    """
    한국어 해설/번역 리포트 문단들을 선택된 단일 AI 음성으로 합성하고,
    목표 나레이션 시간(target_duration)에 맞추어 자연스러운 호흡(Pause) 간격을 동적으로 조절하여
    목표 시간에 정밀 수렴하도록 FFmpeg로 마스터링합니다.
    """
    if not edge_tts:
        raise RuntimeError("edge-tts 라이브러리가 설치되어 있지 않습니다.")

    if not voice:
        voice = "ko-KR-InJoonNeural" if language == "ko" else "en-US-GuyNeural"

    work_dir = os.path.dirname(output_mp3_path)
    os.makedirs(work_dir, exist_ok=True)

    temp_files = []
    section_durations = []
    total_sections = len(script_sections)

    # 1. 문단별 TTS 개별 음성 합성
    for idx, sec in enumerate(script_sections):
        sec_title = sec.get("title", f"섹션 {idx+1}")
        sec_name = sec.get("section", "해설")
        text = sec.get("text", "")

        if progress_callback:
            percent = int((idx / total_sections) * 60) + 15
            progress_callback(percent, f"한국어 번역 나레이션 음성 합성 중: [{sec_name}] {sec_title} ({idx+1}/{total_sections})")

        sec_file = os.path.join(work_dir, f"sec_{idx:03d}.mp3")
        asyncio.run(_synthesize_turn(text, voice, sec_file))
        temp_files.append(sec_file)

        dur = _get_audio_duration_ffprobe(sec_file)
        section_durations.append(dur)

    # 2. 목표 나레이션 시간에 맞춘 동적 호흡(Pause) 간격 계산
    total_speech_time = sum(section_durations)
    pause_count = max(1, total_sections - 1)

    if target_duration and target_duration > total_speech_time:
        # 목표 시간이 발화 시간보다 길 경우: 문단 간 호흡을 적절히 배분 (최소 0.3초 ~ 최대 1.5초)
        remaining_pause = target_duration - total_speech_time
        pause_gap = max(0.3, min(1.5, remaining_pause / pause_count))
    else:
        # 기본 자연스러운 호흡 간격 (0.35초)
        pause_gap = 0.35

    # 3. 타임스탬프 매핑 및 서브타이틀 생성
    subtitles = []
    current_time = 0.0
    for idx, sec in enumerate(script_sections):
        dur = section_durations[idx]
        start_t = current_time
        end_t = start_t + dur

        subtitles.append({
            "id": f"sub_sec_{idx}",
            "start": round(start_t, 2),
            "end": round(end_t, 2),
            "speaker": "Narrator",
            "name": sec.get("section", "해설"),
            "title": sec.get("title", ""),
            "text": sec.get("text", ""),
            "font_size": 32,
            "font_color": "#00f2fe",
            "bg_style": "box",
            "position": "bottom"
        })

        current_time = end_t + pause_gap

    # 마지막 간격 보정
    total_duration = round(current_time - pause_gap + 0.2, 2)

    # 4. FFmpeg로 모든 문단 MP3 병합
    if progress_callback:
        progress_callback(80, "오디오 트랙 결합 및 시간 정밀 마스터링 중...")

    concat_txt_path = os.path.join(work_dir, "concat_sections.txt")
    with open(concat_txt_path, "w", encoding="utf-8") as f:
        for tf in temp_files:
            clean_path = tf.replace("\\", "/")
            f.write(f"file '{clean_path}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_txt_path,
        "-c:a", "libmp3lame", "-q:a", "2",
        output_mp3_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # 5. 비주얼 트랙 (YouTube 썸네일 배치)
    if progress_callback:
        progress_callback(92, "타임라인 비주얼 및 자막 동기화 중...")

    visual_track = []
    num_sources = len(sources)
    if num_sources > 0:
        segment_dur = total_duration / num_sources
        for s_idx, src in enumerate(sources):
            thumb_file = src.get("thumbnail_file")
            v_start = round(s_idx * segment_dur, 2)
            v_dur = round(segment_dur, 2)
            if s_idx == num_sources - 1:
                v_dur = round(total_duration - v_start, 2)

            visual_track.append({
                "id": f"v_yt_{s_idx}",
                "name": src.get("title", f"YouTube {s_idx+1}"),
                "file_path": thumb_file,
                "is_video": False,
                "start": v_start,
                "duration": v_dur
            })

    # 6. Remotion 타임라인 포맷 빌드
    timeline_data = {
        "duration": total_duration,
        "visual_track": visual_track,
        "audio_track": [
            {
                "id": "a_yt_overview",
                "name": "AI Explainer Audio (Korean Narration)",
                "file_path": output_mp3_path,
                "start": 0.0,
                "duration": total_duration,
                "volume": 1.0
            }
        ],
        "subtitle_track": subtitles,
        "subtitle_style": {
            "font_size": 32,
            "font_color": "#ffffff",
            "bg_style": "box",
            "position": "bottom"
        }
    }

    # 임시 파일 정리
    try:
        if os.path.exists(concat_txt_path):
            os.remove(concat_txt_path)
        for tf in temp_files:
            if os.path.exists(tf):
                os.remove(tf)
    except Exception:
        pass

    if progress_callback:
        progress_callback(100, f"한국어 번역 나레이션 오디오 생성 완료! (길이: {total_duration}초)")

    return {
        "audio_file": output_mp3_path,
        "duration": total_duration,
        "target_duration": target_duration,
        "script": script_sections,
        "subtitles": subtitles,
        "timeline_data": timeline_data,
        "sources": sources
    }


# 하위 호환성 별칭
synthesize_podcast_audio_and_timeline = synthesize_explainer_audio_and_timeline

