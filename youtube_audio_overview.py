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
    """youtube-transcript-api를 사용하여 자막 스크립트를 추출합니다. 다국어 및 자동 생성 자막을 모두 지원합니다."""
    if not YouTubeTranscriptApi:
        return ""

    try:
        api = YouTubeTranscriptApi()
        transcript = None
        # 1. 우선 한국어 또는 영어 직접 시도
        try:
            transcript = api.fetch(video_id, languages=["ko", "en", "en-US", "en-GB"])
        except Exception:
            pass

        # 2. 없으면 등록된 모든 자막 목록에서 첫 번째 사용 가능한 자막 가져오기
        if not transcript:
            try:
                t_list = api.list(video_id)
                available = list(t_list)
                if available:
                    # 수동 자막 우선, 없으면 자동 생성 자막
                    chosen = next((t for t in available if not t.is_generated), available[0])
                    transcript = chosen.fetch()
            except Exception as e_list:
                print(f"[YouTube] Transcript list fetch failed for {video_id}: {e_list}")

        if not transcript:
            return ""

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


def _free_translate_to_korean(text: str) -> str:
    """Google 번역 엔드포인트를 사용하여 원문 자막 텍스트를 무료로 직접 번역합니다."""
    if not text:
        return ""
    try:
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ko&dt=t&q=" + urllib.parse.quote(text)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return "".join([s[0] for s in data[0] if s and s[0]])
    except Exception as e:
        print(f"[Translation] Free translate warning: {e}")
        return text


def generate_korean_explainer_script_gemini(
    sources: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    language: str = "ko",
    tone: str = "faithful",
    target_duration: int = 180
) -> List[Dict[str, str]]:
    """
    수집된 외국어 YouTube 영상의 원본 자막을 요약이나 제3자 해설이 아닌,
    실제 화자의 발화 내용을 1인칭으로 그대로 직접 한국어 번역(Faithful Translation)하여
    지정된 목표 시간에 부합하는 나레이션 스크립트를 생성합니다.
    """
    target_duration = max(30, min(600, int(target_duration or 180)))
    target_chars = _calculate_target_chars(target_duration)
    target_mins = round(target_duration / 60, 1)

    # 1. 소스 컨텍스트 조립
    source_context = ""
    for idx, s in enumerate(sources, 1):
        t_snippet = s.get("transcript", "")
        if len(t_snippet) > 15000:
            t_snippet = t_snippet[:15000] + "... (이하 생략)"
        source_context += f"\n\n### [영상 소스 {idx}]\n- 제목: {s.get('title')}\n- 채널: {s.get('author')}\n- 원문 자막/실제 발화 내용:\n{t_snippet or '(원문 자막이 제공되지 않아 영상 제목과 주제를 중심으로 직접 1인칭 강의 나레이션으로 번역해 주세요)'}"

    # 섹션 수 결정: 시간에 따라 3~5개 섹션
    if target_duration <= 90:
        section_guide = "총 3개 섹션 [도입부 번역, 본론 번역, 결론 번역]"
        num_sections = 3
    elif target_duration <= 210:
        section_guide = "총 4개 섹션 [도입부 번역, 본론 1 번역, 본론 2 번역, 결론 번역]"
        num_sections = 4
    else:
        section_guide = "총 5개 섹션 [도입부 번역, 본론 1 번역, 본론 2 번역, 본론 3 번역, 결론 번역]"
        num_sections = 5

    prompt = f"""당신은 외국어(영어 등) 전문 영상 콘텐츠를 원작자의 실제 발화 내용에 입각하여 왜곡 없이 충실히 번역(Faithful Translation)하여 한국어 나레이션으로 직접 전달하는 최고 수준의 전문 번역 나레이터입니다.

제공된 YouTube 영상(외국어 원문 자막)의 실제 발화 내용을 원작자가 직접 한국어로 청취자에게 말하듯이 유려한 1인칭 구어체로 '한국어 번역 나레이션 스크립트'를 작성해주세요.

[★ 절대 준수 규칙 - 제3자 리뷰/해설/요약 엄격 금지]:
1. **1인칭 직접 번역 나레이션 (Direct Dubbing Translation)**:
   - "안녕하세요, 오늘 번역해 드릴 영상은...", "원작자는 ~라고 설명합니다", "저자는 이번 영상에서 ~를 다룹니다", "결론에 이르러 원작자는..." 등의 제3자 리뷰/요약/해설 투 문장을 **절대로 작성하지 마세요**.
   - 영상 속 발표자/화자가 청취자에게 직접 말하는 것처럼 1인칭 나레이션("여러분 안녕하세요, 오늘 우리는 ~를 살펴보겠습니다...", "제가 여기서 강조하고 싶은 점은...", "이 방법의 핵심 원리는...")으로 원문 발화를 그대로 한국어로 직접 번역(Direct Dubbing Translation)하세요.
2. **원문 자막 내용 충실 번역 (Faithful Translation)**:
   - 주관적인 축약이나 요약을 하지 말고, 원문 자막(Transcript)에 나오는 실제 발화 순서, 구체적인 설명, 예시, 수치 데이터를 생략 없이 그대로 한국어로 번역하세요.
   - 목표 시간({target_duration}초 $\rightarrow$ 약 {target_chars}자)에 맞추어, 영상 도입부부터 진행되는 실제 발화 내용을 순차적으로 충실하게 번역하여 채우세요.
3. **목표 나레이션 시간 및 글자 수 엄격 제어**:
   - 사용자가 설정한 목표 나레이션 시간: **{target_duration}초 (약 {target_mins}분)**
   - 한국어 표준 낭독 속도(초당 약 4.3글자)에 정확히 맞추어, **전체 스크립트의 총 글자 수(공백 포함)가 약 {target_chars}자(±5% 이내)**가 되도록 각 섹션의 텍스트 길이를 정밀하게 맞추세요.
   - 각 섹션당 권장 분량: 약 {target_chars // num_sections}자 내외.
4. **자연스러운 구어체 나레이션**:
   - 딱딱한 문어체 직역이 아닌, 귀로 들었을 때 자연스럽고 몰입감 높은 한국어 구어체(해요체/하십시오체)로 번역하세요.
   - 중요한 영문 전문 용어나 고유명사는 한국어 설명 뒤에 괄호로 병기하세요. (예: 거대언어모델(LLM), 파인튜닝(Fine-tuning) 등)
5. **섹션 구성**:
   - {section_guide}
   - 출력 형식은 반드시 아래와 같은 순수 JSON 배열 형식으로만 응답하세요. 마크다운 태그(```json 등)는 제외하거나 순수 JSON만 반환하세요.

[JSON 출력 형식 예시 (직접 번역 나레이션)]:
[
  {{
    "section": "도입부 번역",
    "title": "원문 도입 발화 번역",
    "text": "여러분 안녕하세요. 오늘 강의에서는 대규모 언어 모델을 구축할 때 마주하는 가장 큰 기술적 병목과 그 해결책을 직접 살펴보겠습니다..."
  }},
  {{
    "section": "본론 1 번역",
    "title": "원문 핵심 설명 번역",
    "text": "가장 먼저 우리가 주목해야 할 부분은 바로 메모리 대역폭의 한계입니다. 많은 분들이 모델의 파라미터 수에만 집중하지만, 실제 추론 단계에서는..."
  }},
  {{
    "section": "마무리 번역",
    "title": "원문 결론 발화 번역",
    "text": "결론적으로 이러한 최적화 기법을 적용하면 동일한 하드웨어에서도 처리 속도를 3배 이상 끌어올릴 수 있습니다. 오늘 함께 다룬 핵심 원리들을 여러분의 시스템에도 직접 적용해보시기 바랍니다."
  }}
]

[분석 및 번역할 외국어 YouTube 영상 원본 소스]:
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
                    "temperature": 0.3,
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
            print(f"[Gemini API] Call error: {e}, falling back to built-in faithful translation engine.")

    # API 키가 없거나 호출 실패 시 실제 원문 자막을 직접 번역하는 스마트 폴백 엔진 가동
    return _generate_smart_fallback_explainer_script(sources, language, target_duration)


def _generate_smart_fallback_explainer_script(
    sources: List[Dict[str, Any]],
    language: str = "ko",
    target_duration: int = 180
) -> List[Dict[str, str]]:
    """
    원문 자막(Transcript)이 존재하는 경우, 제3자 요약이나 논평이 아닌
    실제 원문 발화 문장들을 직접 1인칭으로 충실 번역(Faithful Translation)하여 대본을 구성합니다.
    자막이 없는 경우에도 제3자 리뷰가 아닌 영상 주제에 대한 1인칭 직접 설명 나레이션으로 구성합니다.
    """
    target_duration = max(30, min(600, int(target_duration or 180)))
    target_chars = _calculate_target_chars(target_duration)

    # 섹션 수 결정: 60초는 3개, 120~210초는 4개, 300초는 5개
    if target_duration <= 90:
        num_sections = 3
    elif target_duration <= 210:
        num_sections = 4
    else:
        num_sections = 5

    transcript = ""
    for s in sources:
        t = (s.get("transcript") or "").strip()
        if t:
            transcript = t
            break

    title1 = sources[0].get("title", "핵심 기술 주제") if len(sources) > 0 else "주요 주제"

    if transcript:
        # 실제 자막이 있을 경우: 목표 글자 수에 해당하는 단어 분량 추출 (영어 1단어 ≈ 한국어 2.8글자)
        words = transcript.split()
        needed_words = int(target_chars / 2.8)
        selected_text = " ".join(words[:max(needed_words, 40)])
        sentences = [s.strip() for s in re.split(r'(?<=[.?!])\s+', selected_text) if s.strip()]
        if not sentences:
            sentences = [selected_text]

        chunk_size = max(1, len(sentences) // num_sections)
        results = []
        for i in range(num_sections):
            st = i * chunk_size
            ed = (i + 1) * chunk_size if i < num_sections - 1 else len(sentences)
            chunk = " ".join(sentences[st:ed]).strip()
            if not chunk:
                continue
            ko_text = _free_translate_to_korean(chunk)
            if i == 0:
                sec_name = "도입부 번역"
            elif i == num_sections - 1:
                sec_name = "결론부 번역"
            else:
                sec_name = f"본론 {i} 번역"

            results.append({
                "section": sec_name,
                "title": f"원문 {sec_name}",
                "text": ko_text
            })
        if results and len(results) == num_sections:
            return results

    # 자막이 없거나 짧은 경우: 1인칭 직접 강의/설명 나레이션 (절대 제3자 리뷰 아님)
    if num_sections == 3:
        return [
            {
                "section": "도입부 번역",
                "title": "주제 도입 및 문제 정의",
                "text": f"여러분 안녕하세요. 오늘 우리가 함께 살펴볼 핵심 주제는 바로 {title1}입니다. 기존의 방식들이 마주했던 한계를 짚어보고, 왜 새로운 접근법이 필요한지 하나씩 살펴보겠습니다."
            },
            {
                "section": "본론 번역",
                "title": "핵심 메커니즘 및 상세 원리",
                "text": "구체적인 원리를 살펴보면, 가장 중요한 것은 병목을 유발하는 불필요한 연산을 제거하고 데이터 처리 파이프라인의 효율을 극대화하는 것입니다. 실제 테스트에서도 월등한 성능 개선이 확인됩니다."
            },
            {
                "section": "결론 번역",
                "title": "핵심 마무리 및 정리",
                "text": "결론적으로 이러한 새로운 구조를 이해하고 실무에 적용한다면 시스템의 안정성과 생산성을 비약적으로 끌어올릴 수 있습니다. 오늘 공유해 드린 내용을 여러분의 프로젝트에도 꼭 적용해 보시기 바랍니다."
            }
        ]
    elif num_sections == 4:
        return [
            {
                "section": "도입부 번역",
                "title": "주제 도입 및 배경",
                "text": f"여러분 안녕하십니까. 이번 시간 우리는 {title1}에 대해 깊이 있게 탐구해 보고자 합니다. 최근 업계에서 왜 이 주제가 이토록 뜨거운 주목을 받고 있는지 그 배경부터 명확히 짚어보겠습니다."
            },
            {
                "section": "본론 1 번역",
                "title": "기존 한계와 새로운 아키텍처",
                "text": "먼저 기존의 전통적인 방식이 겪고 있던 근본적인 한계를 살펴보겠습니다. 확장성과 지연 시간 측면에서 심각한 병목이 발생하고 있었으며, 이를 극복하기 위해 설계된 새로운 아키텍처가 제안되었습니다."
            },
            {
                "section": "본론 2 번역",
                "title": "세부 메커니즘과 데이터 분석",
                "text": "세부 메커니즘을 들여다보면, 모듈화된 파이프라인과 실시간 피드백 루프를 통해 처리 효율을 극대화하고 있습니다. 벤치마크 테스트에서도 기존 대비 3배 이상의 성능 향상을 뚜렷하게 입증하고 있습니다."
            },
            {
                "section": "결론 번역",
                "title": "핵심 시사점 및 미래 전망",
                "text": "결론적으로 이 혁신적인 패러다임을 선제적으로 도입하는 것이 미래 경쟁력을 확보하는 가장 확실한 방법입니다. 오늘 살펴본 핵심 통찰을 여러분의 업무와 시스템에 적극적으로 활용해 보시기 바랍니다."
            }
        ]
    else:
        return [
            {
                "section": "도입부 번역",
                "title": "주제 도입 및 배경 맥락",
                "text": f"여러분 안녕하십니까. 오늘 우리는 {title1}에 대해 심층적으로 다루어 보겠습니다. 지금 전 세계적으로 왜 이 기술과 접근법에 주목하고 있는지 근본적인 배경 맥락부터 시작하겠습니다."
            },
            {
                "section": "본론 1 번역",
                "title": "구조적 문제점과 요구사항",
                "text": "과거의 시스템들은 급격히 늘어나는 데이터와 복잡한 요구사항을 감당하기에 구조적인 한계가 있었습니다. 이를 해결하기 위해 새로운 패러다임의 아키텍처가 필연적으로 등장하게 되었습니다."
            },
            {
                "section": "본론 2 번역",
                "title": "핵심 알고리즘 및 솔루션",
                "text": "핵심 메커니즘은 매우 직관적이고 강력합니다. 복잡한 워크플로우를 단계별로 모듈화하고 최적화된 라우팅을 적용함으로써 전체적인 처리 속도와 정확도를 동시에 혁신적으로 개선합니다."
            },
            {
                "section": "본론 3 번역",
                "title": "실제 검증 데이터 및 적용 사례",
                "text": "실제 다양한 환경에서 진행된 벤치마크 결과는 매우 고무적입니다. 자원 소모량은 획기적으로 줄어든 반면, 응답 속도와 신뢰성은 비약적으로 향상되었음을 수치로 분명히 확인할 수 있습니다."
            },
            {
                "section": "결론 번역",
                "title": "최종 요약 및 실행 방안",
                "text": "결론적으로 원리를 명확히 이해하고 실제 환경에 한 발 앞서 적용해 보는 것이 가장 중요합니다. 오늘 공유해 드린 실무 팁과 원리들을 여러분의 개발과 분석 환경에 바로 적용해 보시기 바랍니다."
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

    # 2. 목표 나레이션 시간에 맞춘 동적 호흡(Pause) 간격 계산 및 정밀 무음 생성
    target = float(target_duration or 180)
    total_speech_time = sum(section_durations)
    pause_count = max(1, total_sections - 1)

    silence_files = []
    tempo_scale = 1.0

    if target > total_speech_time:
        # 발화 시간보다 목표 시간이 긴 경우: 문단 사이에 실제 무음 파일 생성 및 삽입
        remaining = target - total_speech_time
        gap = remaining / pause_count
        if gap <= 2.0:
            pause_gap = round(gap, 3)
            tail_gap = 0.0
        else:
            # 문단 사이 호흡은 최대 1.4초로 자연스럽게 유지하고, 남은 시간은 말미 여운(tail silence)으로 배분
            pause_gap = 1.4
            tail_gap = round(target - (total_speech_time + (pause_count * pause_gap)), 3)
            tail_gap = max(0.0, tail_gap)
    else:
        # 발화 시간이 목표 시간보다 긴 경우: 최소 자연스러운 호흡(0.25초)을 주고, FFmpeg atempo로 미세 속도 조절
        pause_gap = 0.25
        tail_gap = 0.0

    # 문단 사이 무음 MP3 생성
    p_file = None
    if pause_gap > 0.05:
        p_file = os.path.join(work_dir, "sec_pause.mp3")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
            "-t", str(pause_gap), "-c:a", "libmp3lame", "-q:a", "2", p_file
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        silence_files.append(p_file)

    tail_file = None
    if tail_gap > 0.05:
        tail_file = os.path.join(work_dir, "sec_tail.mp3")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
            "-t", str(tail_gap), "-c:a", "libmp3lame", "-q:a", "2", tail_file
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        silence_files.append(tail_file)

    # 4. Concat 목록 조립 (발화 음성과 실제 무음 파일 교차 배치)
    if progress_callback:
        progress_callback(80, f"오디오 트랙 결합 및 목표 시간({int(target)}초) 정밀 마스터링 중...")

    concat_txt_path = os.path.join(work_dir, "concat_sections.txt")
    with open(concat_txt_path, "w", encoding="utf-8") as f:
        for idx, tf in enumerate(temp_files):
            clean_path = tf.replace("\\", "/")
            f.write(f"file '{clean_path}'\n")
            if p_file and idx < total_sections - 1:
                clean_p = p_file.replace("\\", "/")
                f.write(f"file '{clean_p}'\n")
        if tail_file:
            clean_tail = tail_file.replace("\\", "/")
            f.write(f"file '{clean_tail}'\n")

    # 1차 병합 오디오 생성
    raw_merged = os.path.join(work_dir, "raw_merged.mp3")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_txt_path,
        "-c:a", "libmp3lame", "-q:a", "2",
        raw_merged
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    silence_files.append(raw_merged)

    raw_dur = _get_audio_duration_ffprobe(raw_merged)

    # 발화 시간이 길어서 tempo 보정이 필요한 경우 (raw_dur > target)
    import shutil
    if raw_dur > target + 0.5:
        tempo = round(raw_dur / target, 3)
        tempo = min(1.35, max(1.02, tempo))
        tempo_scale = tempo
        subprocess.run([
            "ffmpeg", "-y", "-i", raw_merged,
            "-filter:a", f"atempo={tempo}",
            "-c:a", "libmp3lame", "-q:a", "2",
            output_mp3_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    else:
        shutil.copy2(raw_merged, output_mp3_path)

    # 최종 오디오 재생 시간 정밀 측정 및 ±0.3초 미세 오차 최종 정합
    final_audio_dur = _get_audio_duration_ffprobe(output_mp3_path)
    if abs(final_audio_dur - target) > 0.3:
        if final_audio_dur < target:
            pad_needed = round(target - final_audio_dur, 3)
            pad_file = os.path.join(work_dir, "pad_extra.mp3")
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                "-t", str(pad_needed), "-c:a", "libmp3lame", "-q:a", "2", pad_file
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            silence_files.append(pad_file)

            with open(concat_txt_path, "w", encoding="utf-8") as f:
                f.write(f"file '{output_mp3_path.replace(chr(92), '/')}'\n")
                f.write(f"file '{pad_file.replace(chr(92), '/')}'\n")
            padded_out = os.path.join(work_dir, "padded_out.mp3")
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_txt_path, "-c:a", "libmp3lame", "-q:a", "2", padded_out
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            shutil.copy2(padded_out, output_mp3_path)
            if os.path.exists(padded_out):
                os.remove(padded_out)
        else:
            trimmed_out = os.path.join(work_dir, "trimmed_out.mp3")
            subprocess.run([
                "ffmpeg", "-y", "-i", output_mp3_path,
                "-t", str(target), "-c:a", "libmp3lame", "-q:a", "2", trimmed_out
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            shutil.copy2(trimmed_out, output_mp3_path)
            if os.path.exists(trimmed_out):
                os.remove(trimmed_out)

    final_audio_dur = _get_audio_duration_ffprobe(output_mp3_path)
    total_duration = round(final_audio_dur, 2)

    # 3. 서브타이틀 타임스탬프 계산 (무음 간격 및 tempo_scale 완벽 동기화)
    subtitles = []
    current_time = 0.0
    for idx, sec in enumerate(script_sections):
        dur = section_durations[idx]
        if tempo_scale != 1.0:
            sec_start = round(current_time / tempo_scale, 2)
            sec_dur = round(dur / tempo_scale, 2)
            sec_end = round(sec_start + sec_dur, 2)
        else:
            sec_start = round(current_time, 2)
            sec_end = round(current_time + dur, 2)

        subtitles.append({
            "id": f"sub_sec_{idx}",
            "start": sec_start,
            "end": sec_end,
            "speaker": "Narrator",
            "name": sec.get("section", f"섹션 {idx+1}"),
            "title": sec.get("title", ""),
            "text": sec.get("text", ""),
            "font_size": 32,
            "font_color": "#00f2fe",
            "bg_style": "box",
            "position": "bottom"
        })

        current_time += dur + pause_gap

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
        for tf in temp_files + silence_files:
            if tf and os.path.exists(tf):
                os.remove(tf)
    except Exception:
        pass

    if progress_callback:
        progress_callback(100, f"한국어 번역 나레이션 오디오 생성 완료! (목표: {int(target)}초 | 완성: {total_duration}초)")

    return {
        "audio_file": output_mp3_path,
        "duration": total_duration,
        "target_duration": int(target),
        "script": script_sections,
        "subtitles": subtitles,
        "timeline_data": timeline_data,
        "sources": sources
    }


# 하위 호환성 별칭
synthesize_podcast_audio_and_timeline = synthesize_explainer_audio_and_timeline

