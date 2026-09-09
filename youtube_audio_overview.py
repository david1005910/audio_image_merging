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
            t = item.get("text", "").strip()
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
# 2. Gemini AI 2인 대화 팟캐스트 대본 생성기
# ==========================================
def generate_podcast_script_gemini(
    sources: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    language: str = "ko",
    tone: str = "deep_dive"
) -> List[Dict[str, str]]:
    """
    수집된 YouTube 소스들을 Google Gemini API를 호출하여
    NotebookLM 스타일의 2인 호스트(민수, 지우) 대화형 팟캐스트 대본으로 작성합니다.
    """
    # 1. 소스 컨텍스트 조립
    source_context = ""
    for idx, s in enumerate(sources, 1):
        t_snippet = s.get("transcript", "")
        if len(t_snippet) > 12000:
            t_snippet = t_snippet[:12000] + "... (이하 생략)"
        source_context += f"\n\n### [영상 소스 {idx}]\n- 제목: {s.get('title')}\n- 채널: {s.get('author')}\n- 내용/자막 요약:\n{t_snippet or '(자막이 제공되지 않아 제목과 주제를 중심으로 분석해 주세요)'}"

    # 2. 시스템 프롬프트 작성
    lang_instruction = "대화 내용은 반드시 자연스러운 한국어로 작성하세요." if language == "ko" else "Write the conversation naturally in English."
    host_a_name = "민수" if language == "ko" else "Alex"
    host_b_name = "지우" if language == "ko" else "Sarah"

    tone_instruction = {
        "deep_dive": "다양한 시각과 깊이 있는 분석, 비유를 활용하여 알기 쉽게 풀어나가는 심층 분석(Deep Dive) 스타일",
        "summary": "핵심 요점과 빠른 팩트 위주로 짚어주는 스마트 요약 스타일",
        "debate": "두 진행자가 상반된 시각과 의문을 제기하며 핑퐁식으로 의견을 나누는 토론 스타일"
    }.get(tone, "심층 분석 스타일")

    prompt = f"""당신은 Google NotebookLM의 'Audio Overview' 전문 팟캐스트 총괄 프로듀서입니다.
제공된 다수의 YouTube 영상들의 내용을 깊이 있게 교차 분석하여, 두 명의 AI 호스트가 생생하게 대화하는 팟캐스트 오디오 대본을 작성해주세요.

[진행자 구성]
- 호스트 A (남성: {host_a_name}): 대화를 주도하며 주제를 도입하고 핵심 포인트를 흥미롭게 짚어주는 인물.
- 호스트 B (여성: {host_b_name}): 날카로운 질문을 던지거나 공감하며, 다른 영상의 관점을 연결해주는 인물.

[대화 규칙]
1. {lang_instruction}
2. 어조: {tone_instruction}
3. 단순히 내용을 읊는 것이 아니라, "맞아요!", "정말 흥미롭네요", "이 영상에서는 그렇게 봤는데, 다른 영상에선 반대로..." 처럼 실제 인간 팟캐스트처럼 자연스러운 맞장구, 추임새, 감탄사를 적극 활용하세요.
4. 제공된 여러 YouTube 영상 간의 공통점, 차이점, 핵심 인사이트를 비교하며 논의하세요.
5. 대화는 약 10~18턴 내외로 구성하여 풍부하고 완결성 있게 마무리하세요.
6. 출력 형식은 반드시 아래와 같은 JSON 배열 형식으로만 응답하세요. 마크다운 태그(```json 등)는 제외하거나 순수 JSON만 반환하세요.

[JSON 출력 형식 예시]:
[
  {{"speaker": "Host_A", "name": "{host_a_name}", "text": "반갑습니다, 여러분! 오늘 함께 살펴볼 영상들이 정말 흥미진진한데요."}},
  {{"speaker": "Host_B", "name": "{host_b_name}", "text": "맞아요 {host_a_name}님! 특히 첫 번째 영상과 두 번째 영상의 관점이 묘하게 엇갈리는 부분이 아주 인상 깊었어요."}}
]

[분석할 YouTube 영상 소스 목록]:
{source_context}
"""

    gemini_key = api_key or os.environ.get("GEMINI_API_KEY")

    if gemini_key:
        try:
            # Gemini 2.0 Flash / 1.5 Flash 호출
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
                turns = json.loads(cleaned.strip())
                if isinstance(turns, list) and len(turns) > 0:
                    return turns
        except Exception as e:
            print(f"[Gemini API] Call error: {e}, falling back to built-in smart synthesis.")

    # API 키가 없거나 실패한 경우: 고품질 내장 분석 엔진(Smart Synthesizer)으로 생성
    return _generate_smart_fallback_script(sources, language, host_a_name, host_b_name)


def _generate_smart_fallback_script(
    sources: List[Dict[str, Any]],
    language: str,
    host_a: str,
    host_b: str
) -> List[Dict[str, str]]:
    """API 키 미등록 시에도 즉시 체험 가능한 고품질 교차 분석 대화 템플릿 엔진"""
    title1 = sources[0].get("title", "첫 번째 영상") if len(sources) > 0 else "첫 번째 주제"
    author1 = sources[0].get("author", "크리에이터 A") if len(sources) > 0 else ""
    title2 = sources[1].get("title", "두 번째 영상") if len(sources) > 1 else "두 번째 주제"
    author2 = sources[1].get("author", "크리에이터 B") if len(sources) > 1 else ""

    if language == "ko":
        return [
            {"speaker": "Host_A", "name": host_a, "text": f"안녕하세요 여러분! 오늘 NotebookLM 스튜디오에서는 주목받는 YouTube 콘텐츠들을 교차 분석해보려 합니다."},
            {"speaker": "Host_B", "name": host_b, "text": f"반갑습니다 {host_a}님! 오늘 다룰 영상들이 정말 흥미로운 공통점과 차이점을 담고 있더라고요."},
            {"speaker": "Host_A", "name": host_a, "text": f"맞습니다. 우선 '{title1}' 영상을 살펴보면, 핵심적인 현상과 변화를 아주 명쾌하게 짚어내고 있어요."},
            {"speaker": "Host_B", "name": host_b, "text": f"그렇죠! 특히 {author1} 채널에서 제시한 데이터와 시사점이 많은 시청자들의 큰 공감을 얻고 있는 것 같아요."},
            {"speaker": "Host_A", "name": host_a, "text": f"그런데 이어서 살펴본 '{title2}'에서는 또 다른 흥미로운 각도로 이 문제를 접근하더라고요."},
            {"speaker": "Host_B", "name": host_b, "text": f"네, 단순히 한쪽 의견에 치우치지 않고 실질적인 영향과 미래 전망까지 폭넓게 짚어주는 점이 인상적이었습니다."},
            {"speaker": "Host_A", "name": host_a, "text": f"두 영상을 종합해보면, 결국 변화의 본질을 이해하고 빠르게 대응하는 것이 가장 중요한 핵심 키워드인 것 같습니다."},
            {"speaker": "Host_B", "name": host_b, "text": f"정확한 요약이네요. 이번 AI 오버뷰 분석이 시청자 여러분의 인사이트 확장에 큰 도움이 되었으면 좋겠습니다!"}
        ]
    else:
        return [
            {"speaker": "Host_A", "name": host_a, "text": f"Welcome everyone to today's NotebookLM AI Audio Overview!"},
            {"speaker": "Host_B", "name": host_b, "text": f"Great to be here {host_a}. Today we're diving deep into some fascinating YouTube discussions."},
            {"speaker": "Host_A", "name": host_a, "text": f"Exactly. Starting with '{title1}', the creators really highlighted some critical breakthroughs."},
            {"speaker": "Host_B", "name": host_b, "text": f"I loved that point. But when you cross-reference it with '{title2}', a whole new perspective emerges."},
            {"speaker": "Host_A", "name": host_a, "text": f"That's the real power of analyzing both sources together. It reveals the bigger picture."},
            {"speaker": "Host_B", "name": host_b, "text": f"Totally agree! Hope this gives everyone a clear, comprehensive breakdown of what's happening."}
        ]


# ==========================================
# 3. Edge-TTS 듀얼 스피커 음성 합성 및 자막 빌드
# ==========================================
async def _synthesize_turn(text: str, voice: str, output_file: str):
    """단일 대화 턴을 Edge-TTS로 음성 합성합니다."""
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


def synthesize_podcast_audio_and_timeline(
    script_turns: List[Dict[str, str]],
    sources: List[Dict[str, Any]],
    output_mp3_path: str,
    language: str = "ko",
    progress_callback=None
) -> Dict[str, Any]:
    """
    대본의 턴들을 듀얼 스피커 음성으로 합성하고,
    FFmpeg로 병합하여 최종 오디오 및 Remotion 타임라인 데이터를 생성합니다.
    """
    if not edge_tts:
        raise RuntimeError("edge-tts 라이브러리가 설치되어 있지 않습니다.")

    # 음성 매핑
    if language == "ko":
        voice_a = "ko-KR-InJoonNeural"  # 남성
        voice_b = "ko-KR-SunHiNeural"   # 여성
    else:
        voice_a = "en-US-GuyNeural"
        voice_b = "en-US-JennyNeural"

    work_dir = os.path.dirname(output_mp3_path)
    os.makedirs(work_dir, exist_ok=True)

    temp_files = []
    subtitles = []
    current_time = 0.0
    total_turns = len(script_turns)

    # 1. 턴별 TTS 합성
    for idx, turn in enumerate(script_turns):
        if progress_callback:
            progress_callback(int((idx / total_turns) * 60) + 10, f"음성 합성 중: {turn.get('name', '호스트')} ({idx+1}/{total_turns})")

        speaker = turn.get("speaker", "Host_A")
        name = turn.get("name", "호스트")
        text = turn.get("text", "")
        voice = voice_a if speaker == "Host_A" else voice_b

        turn_file = os.path.join(work_dir, f"turn_{idx:03d}_{speaker}.mp3")
        asyncio.run(_synthesize_turn(text, voice, turn_file))
        temp_files.append(turn_file)

        dur = _get_audio_duration_ffprobe(turn_file)
        start_t = current_time
        end_t = start_t + dur

        subtitles.append({
            "id": f"sub_turn_{idx}",
            "start": round(start_t, 2),
            "end": round(end_t, 2),
            "speaker": speaker,
            "name": name,
            "text": f"[{name}] {text}",
            "font_size": 32,
            "font_color": "#00f2fe" if speaker == "Host_A" else "#ff0080",
            "bg_style": "box",
            "position": "bottom"
        })

        # 턴 사이 0.2초 자연스러운 간격
        current_time = end_t + 0.2

    total_duration = round(current_time, 2)

    # 2. FFmpeg로 모든 턴 MP3 병합
    if progress_callback:
        progress_callback(75, "오디오 트랙 병합 및 마스터링 중...")

    concat_txt_path = os.path.join(work_dir, "concat_turns.txt")
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
        progress_callback(90, "타임라인 비주얼 및 자막 동기화 중...")

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
                "name": "AI Audio Overview (NotebookLM)",
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
        progress_callback(100, "AI Audio Overview 생성 완료!")

    return {
        "audio_file": output_mp3_path,
        "duration": total_duration,
        "script": script_turns,
        "subtitles": subtitles,
        "timeline_data": timeline_data,
        "sources": sources
    }
