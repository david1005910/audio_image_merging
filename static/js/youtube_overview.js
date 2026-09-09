/**
 * youtube_overview.js
 * YouTube Multi-Source AI Audio Overview (NotebookLM Style)
 * Powered by Gemini AI & Edge-TTS Dual-Speaker Synthesis
 */

(function () {
  'use strict';

  class YouTubeOverviewApp {
    constructor() {
      this.activeJobId = null;
      this.pollTimer = null;
      this.lastResult = null;
      this.audioPlayer = null;

      this.dom = {};
    }

    init() {
      this._bindDOMElements();
      this._loadStoredApiKey();
      this._bindEvents();
    }

    _bindDOMElements() {
      this.dom.urlTextarea = document.getElementById('ytUrlsInput');
      this.dom.apiKeyInput = document.getElementById('ytApiKeyInput');
      this.dom.langSelect = document.getElementById('ytLanguageSelect');
      this.dom.toneSelect = document.getElementById('ytToneSelect');
      this.dom.btnGenerate = document.getElementById('btnGenerateYtOverview');

      // Progress / Monitor
      this.dom.monitorBox = document.getElementById('ytMonitorBox');
      this.dom.stageText = document.getElementById('ytStageText');
      this.dom.progressFill = document.getElementById('ytProgressFill');
      this.dom.percentText = document.getElementById('ytPercentText');

      // Results Section
      this.dom.resultSection = document.getElementById('ytResultSection');
      this.dom.audioPlayerEl = document.getElementById('ytAudioPlayer');
      this.dom.sourcesList = document.getElementById('ytSourcesList');
      this.dom.dialogueList = document.getElementById('ytDialogueList');

      // Action Buttons
      this.dom.btnSendToRemotion = document.getElementById('ytBtnSendToRemotion');
      this.dom.btnSendToScene = document.getElementById('ytBtnSendToScene');
      this.dom.btnDownloadAudio = document.getElementById('ytBtnDownloadAudio');
    }

    _loadStoredApiKey() {
      const savedKey = localStorage.getItem('wave_gemini_api_key');
      if (savedKey && this.dom.apiKeyInput) {
        this.dom.apiKeyInput.value = savedKey;
      }
    }

    _bindEvents() {
      if (this.dom.apiKeyInput) {
        this.dom.apiKeyInput.addEventListener('change', (e) => {
          const val = e.target.value.trim();
          if (val) localStorage.setItem('wave_gemini_api_key', val);
          else localStorage.removeItem('wave_gemini_api_key');
        });
      }

      if (this.dom.btnGenerate) {
        this.dom.btnGenerate.addEventListener('click', () => this.startGeneration());
      }

      if (this.dom.btnSendToRemotion) {
        this.dom.btnSendToRemotion.addEventListener('click', () => this.sendToRemotionStudio());
      }

      if (this.dom.btnSendToScene) {
        this.dom.btnSendToScene.addEventListener('click', () => this.sendToSceneStudio());
      }
    }

    async startGeneration() {
      const rawUrls = (this.dom.urlTextarea.value || '').trim();
      if (!rawUrls) {
        alert('분석할 YouTube 영상 링크를 최소 1개 이상 입력해주세요.');
        this.dom.urlTextarea.focus();
        return;
      }

      // Split lines or commas
      const urls = rawUrls
        .split(/[\r\n,]+/)
        .map(u => u.trim())
        .filter(u => u.length > 0);

      if (urls.length === 0) {
        alert('유효한 YouTube URL을 입력해주세요.');
        return;
      }

      const apiKey = (this.dom.apiKeyInput.value || '').trim();
      if (apiKey) {
        localStorage.setItem('wave_gemini_api_key', apiKey);
      }

      const language = this.dom.langSelect ? this.dom.langSelect.value : 'ko';
      const tone = this.dom.toneSelect ? this.dom.toneSelect.value : 'deep_dive';

      // UI state
      this.dom.btnGenerate.disabled = true;
      this.dom.monitorBox.style.display = 'block';
      this.dom.resultSection.style.display = 'none';
      this.dom.progressFill.style.width = '5%';
      this.dom.percentText.textContent = '5%';
      this.dom.stageText.textContent = 'YouTube 영상 목록 분석 준비 중...';

      try {
        const resp = await fetch('/api/youtube/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ urls, api_key: apiKey, language, tone })
        });

        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '생성 요청에 실패했습니다.');

        this.activeJobId = data.id;
        this._startPolling(data.id);
      } catch (err) {
        alert('요청 오류: ' + err.message);
        this.dom.btnGenerate.disabled = false;
        this.dom.monitorBox.style.display = 'none';
      }
    }

    _startPolling(jobId) {
      if (this.pollTimer) clearInterval(this.pollTimer);

      this.pollTimer = setInterval(async () => {
        try {
          const resp = await fetch(`/api/youtube/status?id=${jobId}`);
          const data = await resp.json();

          if (!resp.ok) {
            throw new Error(data.error || '상태 확인 실패');
          }

          const pct = Math.max(5, data.progress || 0);
          this.dom.progressFill.style.width = `${pct}%`;
          this.dom.percentText.textContent = `${pct}%`;
          this.dom.stageText.textContent = data.stage || '처리 중...';

          if (data.status === 'done') {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
            this.dom.btnGenerate.disabled = false;
            this.lastResult = data.result;
            this._renderResults(data.result);
          } else if (data.status === 'error') {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
            this.dom.btnGenerate.disabled = false;
            alert('AI Audio Overview 생성 오류: ' + (data.error || '알 수 없는 오류'));
          }
        } catch (err) {
          console.error(err);
        }
      }, 800);
    }

    _renderResults(result) {
      this.dom.monitorBox.style.display = 'none';
      this.dom.resultSection.style.display = 'block';

      // 1. Audio Player
      if (this.dom.audioPlayerEl && result.audio_url) {
        this.dom.audioPlayerEl.src = result.audio_url;
        this.dom.audioPlayerEl.load();
      }

      if (this.dom.btnDownloadAudio && result.audio_url) {
        this.dom.btnDownloadAudio.href = result.audio_url;
        this.dom.btnDownloadAudio.download = result.audio_url.split('/').pop();
      }

      // 2. Render Sources
      if (this.dom.sourcesList && result.sources) {
        this.dom.sourcesList.innerHTML = '';
        result.sources.forEach((s) => {
          const card = document.createElement('div');
          card.className = 'yt-source-card';
          card.innerHTML = `
            <img src="${s.thumbnail_url || 'https://img.youtube.com/vi/' + s.video_id + '/hqdefault.jpg'}" alt="썸네일" class="yt-source-thumb">
            <div class="yt-source-meta">
              <div class="yt-source-title" title="${s.title}">${s.title}</div>
              <div class="yt-source-channel">${s.author}</div>
            </div>
            <a href="${s.url}" target="_blank" class="yt-source-link" title="YouTube 영상 열기">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/></svg>
            </a>
          `;
          this.dom.sourcesList.appendChild(card);
        });
      }

      // 3. Render 2-Speaker Dialogue Transcript
      if (this.dom.dialogueList && result.subtitles) {
        this.dom.dialogueList.innerHTML = '';
        result.subtitles.forEach((turn) => {
          const isHostA = turn.speaker === 'Host_A';
          const bubble = document.createElement('div');
          bubble.className = `yt-dialogue-bubble ${isHostA ? 'speaker-a' : 'speaker-b'}`;
          bubble.innerHTML = `
            <div class="dialogue-avatar">${isHostA ? '🎙️' : '🎧'}</div>
            <div class="dialogue-body">
              <div class="dialogue-header">
                <span class="dialogue-name">${turn.name}</span>
                <span class="dialogue-timestamp" title="클릭하여 해당 구간 재생">${this._formatSec(turn.start)} ~ ${this._formatSec(turn.end)}</span>
              </div>
              <div class="dialogue-text">${turn.text.replace(/^\[.*?\]\s*/, '')}</div>
            </div>
          `;

          // Click timestamp to seek audio
          bubble.querySelector('.dialogue-timestamp').addEventListener('click', () => {
            if (this.dom.audioPlayerEl) {
              this.dom.audioPlayerEl.currentTime = turn.start;
              this.dom.audioPlayerEl.play();
            }
          });

          this.dom.dialogueList.appendChild(bubble);
        });
      }

      // Smooth scroll into view
      this.dom.resultSection.scrollIntoView({ behavior: 'smooth' });
    }

    _formatSec(sec) {
      const m = Math.floor(sec / 60);
      const s = Math.floor(sec % 60).toString().padStart(2, '0');
      return `${m}:${s}`;
    }

    // ==========================================
    // Bridge to Remotion Multi-Track Studio
    // ==========================================
    sendToRemotionStudio() {
      if (!this.lastResult || !this.lastResult.timeline_data) {
        alert('내보낼 생성 결과가 없습니다.');
        return;
      }

      if (!window.remotionApp) {
        alert('Remotion 스튜디오가 초기화되지 않았습니다.');
        return;
      }

      // Populate Remotion Timeline with YouTube AI Audio Overview Data
      const tl = this.lastResult.timeline_data;
      window.remotionApp.timeline.duration = tl.duration || 15.0;
      window.remotionApp.timeline.visual_track = tl.visual_track || [];
      window.remotionApp.timeline.audio_track = tl.audio_track || [];
      window.remotionApp.timeline.subtitle_track = tl.subtitle_track || [];

      // Create Audio element for playback preview
      if (window.remotionApp.timeline.audio_track.length > 0) {
        const a = window.remotionApp.timeline.audio_track[0];
        a.audioEl = new Audio(this.lastResult.audio_url);
        a.url = this.lastResult.audio_url;
      }

      // Load Image Bitmaps for visual track thumbnails
      window.remotionApp.timeline.visual_track.forEach((v) => {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => {
          v.imgBitmap = img;
          window.remotionApp.renderCanvas();
        };
        // Use local download url or original thumbnail
        const matchSrc = (this.lastResult.sources || []).find(s => s.thumbnail_file === v.file_path);
        if (matchSrc && matchSrc.thumbnail_url) {
          img.src = matchSrc.thumbnail_url;
        } else if (v.file_path) {
          img.src = `/download/${v.file_path.split(/[\\/]/).pop()}`;
        }
      });

      // Switch to Remotion Tab
      const tabBtn = document.getElementById('tabRemotionStudio');
      if (tabBtn) {
        tabBtn.click();
      }

      window.remotionApp.seekTo(0);
      window.remotionApp.renderTimeline();
      window.remotionApp.renderCanvas();

      alert('🎬 Remotion 멀티트랙 스튜디오로 전송되었습니다!\n비주얼(썸네일), 오디오(팟캐스트 음성), 자막(2인 대화록)이 타임라인에 자동 배치되었습니다.');
    }

    // ==========================================
    // Bridge to Multi-Scene Subtitles Studio
    // ==========================================
    sendToSceneStudio() {
      if (!this.lastResult) return;

      const narrationText = document.getElementById('narrationText');
      if (narrationText && this.lastResult.subtitles) {
        const scriptLines = this.lastResult.subtitles.map(s => s.text).join('\n\n');
        narrationText.value = scriptLines;
      }

      const tabScene = document.getElementById('tabSceneStudio');
      if (tabScene) {
        tabScene.click();
      }

      alert('📝 씬 & 나레이션 자막 스튜디오로 대본이 전달되었습니다!');
    }
  }

  window.YouTubeOverviewApp = YouTubeOverviewApp;

  document.addEventListener('DOMContentLoaded', () => {
    window.ytApp = new YouTubeOverviewApp();
    window.ytApp.init();
  });
})();
