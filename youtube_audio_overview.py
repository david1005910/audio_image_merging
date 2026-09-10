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
# 2. Gemini AI 한국어 심층 해설 스크립트 생성기 (Single Explainer)
# ==========================================
def generate_korean_explainer_script_gemini(
    sources: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    language: str = "ko",
    tone: str = "deep_dive"
) -> List[Dict[str, str]]:
    """
    수집된 YouTube 소스(영어/외국어 포함)를 Google Gemini AI로 심층 분석하여
    한국인 청취자가 쉽게 이해할 수 있는 전문 해설가 1인 나레이션 스크립트를 생성합니다.
    """
    # 1. 소스 컨텍스트 조립
    source_context = ""
    for idx, s in enumerate(sources, 1):
        t_snippet = s.get("transcript", "")
        if len(t_snippet) > 12000:
            t_snippet = t_snippet[:12000] + "... (이하 생략)"
        source_context += f"\n\n### [영상 소스 {idx}]\n- 제목: {s.get('title')}\n- 채널: {s.get('author')}\n- 내용/자막 요약:\n{t_snippet or '(자막이 제공되지 않아 제목과 주제를 중심으로 분석해 주세요)'}"

    # 2. 시스템 프롬프트 작성
    tone_instruction = {
        "deep_dive": "배경 지식과 원리를 상세히 풀어서 차근차근 설명해주는 친절한 심층 해설 스타일",
        "summary": "핵심 요약과 팩트 위주로 빠르게 정리해주는 3분 핵심 요약 스타일",
        "actionable": "실무 적용 방안과 핵심 인사이트, 청취자가 바로 써먹을 수 있는 팁 중심 스타일"
    }.get(tone, "심층 해설 스타일")

    prompt = f"""당신은 세계적인 최신 테크 및 지식 콘텐츠를 분석하여 대중에게 알기 쉽게 전달하는 최고 수준의 전문 한국어 해설가(Explainer & Insight Analyst)입니다.
제공된 YouTube 영상들의 내용(영어 또는 외국어 원본 포함)을 꼼꼼히 파악하여, 한국 청취자가 귀로 들었을 때 바로 이해할 수 있는 '한국어 심층 해설 오디오 나레이션 스크립트'를 작성해주세요.

[필수 작성 규칙]:
1. **언어**: 원본 영상이 영어나 외국어이더라도, 해설은 반드시 **자연스럽고 유려한 고품질 한국어**로 작성하세요. 단순 번역이 아니라 맥락과 배경을 살린 설명이어야 합니다.
2. **화자 구성**: 2인 대화(팟캐스트)가 아닌, **단독 1인 전문 해설가의 나레이션(독백)** 형식입니다.
3. **어조**: 신뢰감 있고 친절하며 귀에 쏙쏙 들어오는 구어체 (해요체와 하십시오체를 자연스럽게 혼용, 예: '~합니다', '~인데요', '~살펴보겠습니다').
4. **용어 설명**: 어려운 영문 기술 용어나 개념은 청취자가 알기 쉽게 풀어서 설명하고 필요 시 괄호 병기하세요 (예: 거대언어모델(LLM), 검색증강생성(RAG) 등).
5. **어조/스타일**: {tone_instruction}
6. **섹션 구성**: 약 4~6개의 논리적 문단으로 구성하세요:
   - 1) 도입 (영상 주제 소개 및 이 내용이 왜 중요한지 배경 설명)
   - 2) 핵심 분석 1 (영상 원문이 제시하는 핵심 원리, 주요 주장 및 데이터 해설)
   - 3) 핵심 분석 2 (적용 사례, 한계점 또는 여러 영상 간의 시너지/비교 분석)
   - 4) 결론 및 시사점 (청취자를 위한 핵심 요약 및 최종 인사이트 정리)
7. 출력 형식은 반드시 아래와 같은 JSON 배열 형식으로만 응답하세요. 마크다운 태그(```json 등)는 제외하거나 순수 JSON만 반환하세요.

[JSON 출력 형식 예시]:
[
  {{
    "section": "도입",
    "title": "주제 소개 및 배경",
    "text": "안녕하세요. 오늘 함께 살펴볼 영상은 최근 주목받고 있는 인공지능 에이전트의 발전 흐름을 다룬 콘텐츠입니다."
  }},
  {{
    "section": "핵심 해설 1",
    "title": "원문의 핵심 주장 분석",
    "text": "영상에서는 특히 기존 언어모델의 한계를 극복하기 위해 다중 에이전트 협업 구조가 왜 필수적인지를 실제 벤치마크 데이터를 통해 입증하고 있습니다."
  }},
  {{
    "section": "핵심 해설 2",
    "title": "심층 시사점 및 비교",
    "text": "흥미로운 점은 단순히 모델의 크기만 키우는 것이 아니라, 도구 사용과 피드백 루프를 결합했을 때 성능이 비약적으로 상승한다는 분석입니다."
  }},
  {{
    "section": "결론",
    "title": "핵심 요약 및 총평",
    "text": "결국 이번 영상이 전하는 핵심 메시지는 자동화를 넘어 자율적으로 문제를 해결하는 시스템으로의 패러다임 전환입니다. 여러분의 프로젝트에도 이러한 관점을 적극 접목해보시기 바랍니다."
  }}
]

[분석할 YouTube 영상 소스 목록]:
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
                    "temperature": 0.7,
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

    # API 키가 없거나 호출 실패 시 스마트 폴백 해설 생성
    return _generate_smart_fallback_explainer_script(sources, language)


def _generate_smart_fallback_explainer_script(
    sources: List[Dict[str, Any]],
    language: str = "ko"
) -> List[Dict[str, str]]:
    """API 키 미등록 시에도 즉시 동작하는 고품질 한국어 단독 해설 템플릿 엔진"""
    title1 = sources[0].get("title", "YouTube 영상") if len(sources) > 0 else "주요 영상 콘텐츠"
    author1 = sources[0].get("author", "글로벌 크리에이터") if len(sources) > 0 else ""
    title2 = sources[1].get("title", "두 번째 영상") if len(sources) > 1 else ""
    author2 = sources[1].get("author", "") if len(sources) > 1 else ""

    if language == "ko":
        result = [
            {
                "section": "도입",
                "title": "주제 소개 및 배경",
                "text": f"안녕하세요. 오늘 함께 살펴볼 영상은 {author1} 채널의 '{title1}'입니다. 이 콘텐츠는 최근 업계와 대중의 뜨거운 관심을 받고 있는 핵심 화두를 매우 깊이 있게 다루고 있습니다."
            },
            {
                "section": "핵심 해설 1",
                "title": "원문의 핵심 내용과 논점",
                "text": f"원문 영상의 핵심을 정리해보면, 복잡한 이론이나 기술적 원리를 누구나 직관적으로 이해할 수 있도록 실제 사례와 명확한 근거 데이터를 통해 설명하고 있습니다. 특히 기존의 한계점을 극복하기 위한 새로운 접근법이 매우 인상적입니다."
            }
        ]

        if title2:
            result.append({
                "section": "핵심 해설 2",
                "title": "다중 소스 교차 분석",
                "text": f"또한 이어서 살펴본 {author2}의 '{title2}' 영상과 대조해보면 또 다른 중요한 시사점이 발견됩니다. 첫 번째 영상이 문제 정의와 방법론에 집중했다면, 두 번째 영상은 이를 실질적으로 응용하고 확장하는 방안에 주목하고 있습니다."
            })
        else:
            result.append({
                "section": "핵심 해설 2",
                "title": "심층 시사점 및 실무 가치",
                "text": "영상에서 특히 강조하는 부분은, 단순히 트렌드를 쫓아가는 데 그치지 않고 본질적인 메커니즘을 이해하고 이를 자신의 업무나 프로젝트에 능동적으로 적용하는 통찰력의 중요성입니다."
            })

        result.append({
            "section": "결론",
            "title": "핵심 요약 및 총평",
            "text": "종합해보면, 이번 영상은 새로운 패러다임 속에서 우리가 어떤 방향성을 가지고 준비해야 할지 명쾌한 가이드를 제공합니다. 핵심 포인트를 잘 기억해 두시면 앞으로의 의사결정에 큰 도움이 될 것입니다."
        })
        return result
    else:
        return [
            {
                "section": "Introduction",
                "title": "Overview and Context",
                "text": f"Hello everyone. Today we are breaking down the key insights from '{title1}' by {author1}."
            },
            {
                "section": "Key Analysis",
                "title": "Core Breakdown",
                "text": "The presentation details the critical breakthrough moments, highlighting how recent advancements overcome longstanding bottlenecks."
            },
            {
                "section": "Conclusion",
                "title": "Summary & Takeaways",
                "text": "In conclusion, this video offers an essential roadmap for navigating upcoming changes. Keep these key takeaways in mind as you move forward."
            }
        ]


# 하위 호환성 별칭
generate_podcast_script_gemini = generate_korean_explainer_script_gemini


# ==========================================
# 3. Edge-TTS 단일 해설가 음성 합성 및 타임라인 빌드
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
    progress_callback=None
) -> Dict[str, Any]:
    """
    한국어 해설 리포트 문단들을 선택된 단일 AI 음성으로 합성하고,
    FFmpeg로 병합하여 최종 해설 오디오 및 Remotion 1080p 타임라인을 생성합니다.
    """
    if not edge_tts:
        raise RuntimeError("edge-tts 라이브러리가 설치되어 있지 않습니다.")

    # 기본 음성 결정
    if not voice:
        voice = "ko-KR-InJoonNeural" if language == "ko" else "en-US-GuyNeural"

    work_dir = os.path.dirname(output_mp3_path)
    os.makedirs(work_dir, exist_ok=True)

    temp_files = []
    subtitles = []
    current_time = 0.0
    total_sections = len(script_sections)

    # 1. 문단별 TTS 합성
    for idx, sec in enumerate(script_sections):
        sec_title = sec.get("title", f"섹션 {idx+1}")
        sec_name = sec.get("section", "해설")
        text = sec.get("text", "")

        if progress_callback:
            percent = int((idx / total_sections) * 60) + 15
            progress_callback(percent, f"한국어 해설 음성 합성 중: [{sec_name}] {sec_title} ({idx+1}/{total_sections})")

        sec_file = os.path.join(work_dir, f"sec_{idx:03d}.mp3")
        asyncio.run(_synthesize_turn(text, voice, sec_file))
        temp_files.append(sec_file)

        dur = _get_audio_duration_ffprobe(sec_file)
        start_t = current_time
        end_t = start_t + dur

        subtitles.append({
            "id": f"sub_sec_{idx}",
            "start": round(start_t, 2),
            "end": round(end_t, 2),
            "speaker": "Narrator",
            "name": sec_name,
            "title": sec_title,
            "text": text,
            "font_size": 32,
            "font_color": "#00f2fe",
            "bg_style": "box",
            "position": "bottom"
        })

        # 문단 사이 0.35초의 자연스러운 호흡(Pause) 간격
        current_time = end_t + 0.35

    total_duration = round(current_time, 2)

    # 2. FFmpeg로 모든 문단 MP3 병합
    if progress_callback:
        progress_callback(80, "오디오 트랙 결합 및 마스터링 중...")

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

    # 3. 비주얼 트랙 (YouTube 썸네일 배치)
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

    # 4. Remotion 타임라인 포맷 빌드
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
        progress_callback(100, "AI 한국어 해설 오디오 생성 완료!")

    return {
        "audio_file": output_mp3_path,
        "duration": total_duration,
        "script": script_sections,
        "subtitles": subtitles,
        "timeline_data": timeline_data,
        "sources": sources
    }


# 하위 호환성 별칭
synthesize_podcast_audio_and_timeline = synthesize_explainer_audio_and_timeline
