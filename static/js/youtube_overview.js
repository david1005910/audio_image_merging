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
      this.selectedDuration = 180;
      this.isCustomDuration = false;

      this.dom = {};
    }

    init() {
      this._bindDOMElements();
      this._loadStoredApiKey();
      this._bindEvents();
      this._updateDurationDisplay();
    }

    _bindDOMElements() {
      this.dom.urlTextarea = document.getElementById('ytUrlsInput');
      this.dom.apiKeyInput = document.getElementById('ytApiKeyInput');
      this.dom.voiceSelect = document.getElementById('ytVoiceSelect');
      this.dom.toneSelect = document.getElementById('ytToneSelect');
      this.dom.btnGenerate = document.getElementById('btnGenerateYtOverview');

      // Duration Controls
      this.dom.durationPresetGroup = document.getElementById('ytDurationPresetGroup');
      this.dom.durationPresetBtns = document.querySelectorAll('.btn-duration-preset');
      this.dom.durationValBadge = document.getElementById('ytDurationValBadge');
      this.dom.customDurationRow = document.getElementById('ytCustomDurationRow');
      this.dom.customDurationInput = document.getElementById('ytCustomDurationInput');
      this.dom.charEstimate = document.getElementById('ytCharEstimate');

      // Duration Stat Comparison
      this.dom.statTargetDur = document.getElementById('ytStatTargetDur');
      this.dom.statActualDur = document.getElementById('ytStatActualDur');
      this.dom.statMatchRate = document.getElementById('ytStatMatchRate');

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

      // Duration Presets
      if (this.dom.durationPresetBtns) {
        this.dom.durationPresetBtns.forEach((btn) => {
          btn.addEventListener('click', () => {
            const d = btn.dataset.duration;
            this.dom.durationPresetBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            if (d === 'custom') {
              this.isCustomDuration = true;
              if (this.dom.customDurationRow) this.dom.customDurationRow.style.display = 'block';
              const customSec = parseInt(this.dom.customDurationInput ? this.dom.customDurationInput.value : 180, 10) || 180;
              this.selectedDuration = Math.max(30, Math.min(600, customSec));
            } else {
              this.isCustomDuration = false;
              if (this.dom.customDurationRow) this.dom.customDurationRow.style.display = 'none';
              this.selectedDuration = parseInt(d, 10);
            }
            this._updateDurationDisplay();
          });
        });
      }

      // Custom Duration Input
      if (this.dom.customDurationInput) {
        this.dom.customDurationInput.addEventListener('input', (e) => {
          let val = parseInt(e.target.value, 10);
          if (!isNaN(val)) {
            val = Math.max(30, Math.min(600, val));
            this.selectedDuration = val;
            this._updateDurationDisplay();
          }
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

    _updateDurationDisplay() {
      const sec = this.selectedDuration;
      const min = Math.floor(sec / 60);
      const rem = sec % 60;
      const minText = rem > 0 ? `${min}분 ${rem}초 (${sec}초)` : `${min}분 (${sec}초)`;
      if (this.dom.durationValBadge) {
        this.dom.durationValBadge.textContent = minText;
      }
      const estChars = Math.round(Math.max(25, sec - 1.5) * 4.3);
      if (this.dom.charEstimate) {
        this.dom.charEstimate.textContent = `예상 생성 분량: 약 ${estChars}자 (±10%)`;
      }
    }

    async startGeneration() {
      const rawUrls = (this.dom.urlTextarea.value || '').trim();
      if (!rawUrls) {
        alert('번역할 YouTube 영상 링크를 최소 1개 이상 입력해주세요.');
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

      const voice = this.dom.voiceSelect ? this.dom.voiceSelect.value : 'ko-KR-InJoonNeural';
      const tone = this.dom.toneSelect ? this.dom.toneSelect.value : 'faithful';
      const targetDuration = this.selectedDuration || 180;

      // UI state
      this.dom.btnGenerate.disabled = true;
      this.dom.monitorBox.style.display = 'block';
      this.dom.resultSection.style.display = 'none';
      this.dom.progressFill.style.width = '5%';
      this.dom.percentText.textContent = '5%';
      this.dom.stageText.textContent = `YouTube 영상 분석 및 시간 맞춤형(${targetDuration}초) 번역 준비 중...`;

      try {
        const resp = await fetch('/api/youtube/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            urls,
            api_key: apiKey,
            voice,
            tone,
            language: 'ko',
            target_duration: targetDuration
          })
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

      // Duration comparison stats
      const targetSec = parseInt(result.target_duration || this.selectedDuration || 180, 10);
      const actualSec = parseFloat(result.duration || 0);

      if (this.dom.statTargetDur) {
        const tm = Math.floor(targetSec / 60);
        const ts = targetSec % 60;
        this.dom.statTargetDur.textContent = `${targetSec}초 (${tm}분 ${ts}초)`;
      }
      if (this.dom.statActualDur) {
        const am = Math.floor(actualSec / 60);
        const as = Math.round(actualSec % 60);
        this.dom.statActualDur.textContent = `${actualSec.toFixed(1)}초 (${am}분 ${as}초)`;
      }
      if (this.dom.statMatchRate) {
        const diff = Math.abs(actualSec - targetSec);
        const rate = Math.max(0, Math.min(100, (1 - diff / targetSec) * 100));
        this.dom.statMatchRate.textContent = `${rate.toFixed(1)}%`;
      }

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

      // 3. Render Structured Explanatory Report Cards
      if (this.dom.dialogueList && result.subtitles) {
        this.dom.dialogueList.innerHTML = '';
        result.subtitles.forEach((item, idx) => {
          const card = document.createElement('div');
          card.className = 'yt-explainer-card';
          card.innerHTML = `
            <div class="explainer-card-header">
              <span class="explainer-badge">${item.name || `섹션 ${idx + 1}`}</span>
              <span class="explainer-title">${item.title || ''}</span>
              <button type="button" class="explainer-timestamp" title="클릭하여 해당 구간 오디오 재생">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                <span>${this._formatSec(item.start)} ~ ${this._formatSec(item.end)}</span>
              </button>
            </div>
            <div class="explainer-text">${item.text}</div>
          `;

          // Click timestamp or card to seek audio
          card.querySelector('.explainer-timestamp').addEventListener('click', (e) => {
            e.stopPropagation();
            if (this.dom.audioPlayerEl) {
              this.dom.audioPlayerEl.currentTime = item.start;
              this.dom.audioPlayerEl.play();
            }
          });

          card.addEventListener('click', () => {
            if (this.dom.audioPlayerEl) {
              this.dom.audioPlayerEl.currentTime = item.start;
              this.dom.audioPlayerEl.play();
            }
          });

          this.dom.dialogueList.appendChild(card);
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

      alert('🎬 Remotion 멀티트랙 스튜디오로 전송되었습니다!\n비주얼(썸네일), 오디오(한국어 해설 음원), 자막(한국어 해설 대본)이 타임라인에 자동 배치되었습니다.');
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
