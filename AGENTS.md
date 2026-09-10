# AGENTS.md

Python scripts that shell out to `ffmpeg` to produce 1080p MP4 videos from audio/images.

## Prerequisites
- `ffmpeg` on PATH — no Python packages needed; all scripts use stdlib only (`subprocess`, `os`, `threading`).
- No package manager, manifest, or install step.

## Entry points
- **`webui.py`** — Fullstack HTTP server (stdlib `ThreadingHTTPServer`) with a modern Korean-language studio Web UI (`http://127.0.0.1:8080`). Run: `python webui.py [port]` (default `8080`).
- **`youtube_audio_overview.py`** — Multi-source YouTube transcript extractor, Google Gemini AI Korean explanatory narration generator (for English & multilingual videos), Edge-TTS single-voice audio synthesizer, and Remotion timeline exporter.
- **`remotion_engine.py`** — Remotion-style multi-track timeline video compiler (visual, audio, subtitle tracks) to 1080p MP4.
- **`scene_video.py`** — Multi-scene narration subtitle video generator with auto-sentence distribution.
- `waveform_video.py` — audio → waveform visualization (`showwaves`, `mode=cline`). Supports custom `wave_color` and real-time progress callbacks.
- `waveform_overlay_video.py` — background image + semi-transparent waveform overlay with positioning (top/center/bottom).
- `static_video.py` — still image + audio → MP4 (loop + scale/pad to 1920×1080).
- `batch_convert.py` — CLI tool for batch conversion across directories. Run: `python batch_convert.py --help`.

## Fullstack WebUI Architecture
- **Templates & Static Assets**:
  - `templates/index.html` — Semantic HTML5 studio UI with drag-and-drop, Remotion timeline editor, Scene subtitle editor, YouTube AI Korean Explainer Audio Overview, and in-browser video player modal.
  - `static/css/style.css` — Modern dark glassmorphism design system (`Inter`, `JetBrains Mono`, neon glows, structured explainer report cards).
  - `static/js/app.js` — Frontend state machine, canvas layout mockup renderer, REST API polling, and library manager.
  - `static/js/remotion_editor.js` — Remotion-style multi-track timeline editor frontend engine.
  - `static/js/youtube_overview.js` — Multi-YouTube analyzer, Gemini API key manager, Korean explanatory audio player & interactive report viewer, 1-click Remotion/Scene Studio bridge.
  - `static/js/audio_preview.js` — In-browser Web Audio API waveform visualizer and audio playback previewer.
- **REST API Endpoints**:
  - `GET /` — Serves `templates/index.html`.
  - `GET /static/*` — Serves static CSS, JS, and image assets with MIME type detection.
  - `POST /api/run` — Multipart upload (`audio`, `image`, `tasks`, `wave_color`, `opacity`, `wave_height`, `position`, `remotion_timeline`, `scenes`). Returns `{"id": job_id}`.
  - `GET /api/status?id=<id>` — Returns job status, percentage (0-100%), current task, log output, and results.
  - `POST /api/cancel?id=<id>` — Cancels running job and terminates FFmpeg process.
  - `POST /api/youtube/generate` — JSON payload (`urls`, `gemini_api_key`, `language`, `tone`). Generates 2-host podcast audio + script + Remotion timeline. Returns `{"id": job_id}`.
  - `GET /api/youtube/status?id=<id>` — Returns YouTube job progress, stages, generated audio URL, script, thumbnails, and Remotion timeline data.
  - `GET /api/files` — Returns list of generated MP4 files with metadata.
  - `DELETE /api/files/<name>` — Deletes generated file from `outputs/`.
  - `GET /download/<name>` — Streams video and audio (`.mp4`, `.mp3`, `.jpg`) with HTTP Range header support (`206 Partial Content`).
- `uploads/` and `outputs/` are created at startup and hold per-job artifacts.
- Job queueing uses `RUN_LOCK` (`threading.Lock`) so jobs run sequentially.

## Gotchas
- All default I/O paths for CLI scripts are hardcoded (`input.mp3`, `background.jpg`, `output.mp4`); pass explicit paths or edit the `__main__` block.
- `waveform_overlay_video.py` uses `colorkey` on black (`0x000000`) to make the waveform background transparent — dim or black waveform colors will key out unexpectedly. Keep `wave_color` bright and non-black.
- `libx264` requires even dimensions; odd dimensions are automatically padded to even.
- Web UI messages and error strings are in Korean.
