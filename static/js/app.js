/**
 * app.js
 * WaveStudio Fullstack UI logic, API interaction & Real-time Live Preview
 */

(function () {
  'use strict';

  // Global State
  const state = {
    audioFile: null,
    imageFile: null,
    imageBitmap: null,
    selectedMode: 'waveform_overlay', // 'waveform' | 'waveform_overlay' | 'static'
    batchAll: false,
    waveColor: '#00d2ff',
    opacity: 0.7,
    waveHeight: 320,
    position: 'bottom', // 'top' | 'center' | 'bottom'
    activeJobId: null,
    pollTimer: null,
    audioPreviewer: null
  };

  // Color Presets
  const PRESETS = [
    { name: 'Cyber Cyan', color: '#00d2ff' },
    { name: 'Neon Sunset', color: '#f97316' },
    { name: 'Violet Pulse', color: '#a855f7' },
    { name: 'Emerald Glow', color: '#10b981' },
    { name: 'Pure White', color: '#ffffff' },
    { name: 'Hot Pink', color: '#ff0080' }
  ];

  // DOM Elements
  const el = {};

  document.addEventListener('DOMContentLoaded', () => {
    initDOMElements();
    initAudioPreviewer();
    initPresets();
    initDropzones();
    initModeCards();
    initCustomizerInputs();
    initPreviewCanvas();
    initLogToggle();
    initModal();
    initRunAction();
    fetchLibraryFiles();
  });

  function initDOMElements() {
    el.audioDrop = document.getElementById('audioDrop');
    el.audioInput = document.getElementById('audioInput');
    el.audioLoadedCard = document.getElementById('audioLoadedCard');
    el.audioFileName = document.getElementById('audioFileName');
    el.audioFileSize = document.getElementById('audioFileSize');
    el.btnRemoveAudio = document.getElementById('btnRemoveAudio');

    el.imageDrop = document.getElementById('imageDrop');
    el.imageInput = document.getElementById('imageInput');
    el.imageLoadedCard = document.getElementById('imageLoadedCard');
    el.imageFileName = document.getElementById('imageFileName');
    el.imageFileSize = document.getElementById('imageFileSize');
    el.btnRemoveImage = document.getElementById('btnRemoveImage');
    el.imageThumb = document.getElementById('imageThumb');

    el.modeCards = document.querySelectorAll('.mode-card');
    el.batchToggle = document.getElementById('batchAllToggle');
    el.optionsPanel = document.getElementById('optionsPanel');

    el.presetsContainer = document.getElementById('presetsContainer');
    el.waveColorInput = document.getElementById('waveColorInput');
    el.waveColorHex = document.getElementById('waveColorHex');
    el.opacitySlider = document.getElementById('opacitySlider');
    el.opacityVal = document.getElementById('opacityVal');
    el.heightSlider = document.getElementById('heightSlider');
    el.heightVal = document.getElementById('heightVal');
    el.posButtons = document.querySelectorAll('.segment-btn');

    el.previewCanvas = document.getElementById('previewCanvas');
    el.btnGenerate = document.getElementById('btnGenerate');

    el.monitorPanel = document.getElementById('monitorPanel');
    el.stageBadge = document.getElementById('stageBadge');
    el.percentageText = document.getElementById('percentageText');
    el.progressBar = document.getElementById('progressBar');
    el.btnCancel = document.getElementById('btnCancel');
    el.btnToggleLog = document.getElementById('btnToggleLog');
    el.terminalDrawer = document.getElementById('terminalDrawer');
    el.terminalLog = document.getElementById('terminalLog');
    el.stepPills = document.querySelectorAll('.step-pill');

    el.resultsContainer = document.getElementById('resultsContainer');
    el.resultsList = document.getElementById('resultsList');
    el.libraryGrid = document.getElementById('libraryGrid');

    el.videoModal = document.getElementById('videoModal');
    el.modalVideo = document.getElementById('modalVideo');
    el.modalTitle = document.getElementById('modalTitle');
    el.btnCloseModal = document.getElementById('btnCloseModal');
  }

  function initAudioPreviewer() {
    state.audioPreviewer = new AudioWavePreviewer('audioWaveCanvas', 'btnPlayAudio', 'audioTimeLabel');
  }

  function initPresets() {
    if (!el.presetsContainer) return;
    el.presetsContainer.innerHTML = '';
    PRESETS.forEach(p => {
      const chip = document.createElement('div');
      chip.className = `preset-chip ${p.color.toLowerCase() === state.waveColor.toLowerCase() ? 'active' : ''}`;
      chip.dataset.color = p.color;
      chip.innerHTML = `<span class="preset-dot" style="background:${p.color}"></span>${p.name}`;
      chip.addEventListener('click', () => {
        applyColor(p.color);
        document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
      });
      el.presetsContainer.appendChild(chip);
    });
  }

  function applyColor(hex) {
    state.waveColor = hex;
    el.waveColorInput.value = hex;
    el.waveColorHex.value = hex;
    renderLivePreview();
  }

  function initDropzones() {
    // Audio Dropzone
    setupDropzone(el.audioDrop, el.audioInput, (file) => {
      if (!file.type.startsWith('audio/') && !file.name.match(/\.(mp3|wav|m4a|ogg|flac|aac)$/i)) {
        alert('오디오 파일(.mp3, .wav, .m4a 등)만 업로드 가능합니다.');
        return;
      }
      state.audioFile = file;
      el.audioFileName.textContent = file.name;
      el.audioFileSize.textContent = formatBytes(file.size);
      el.audioDrop.style.display = 'none';
      el.audioLoadedCard.classList.add('active');
      state.audioPreviewer.loadFile(file);
      updateGenerateButtonState();
    });

    el.btnRemoveAudio.addEventListener('click', () => {
      state.audioFile = null;
      el.audioInput.value = '';
      el.audioLoadedCard.classList.remove('active');
      el.audioDrop.style.display = 'flex';
      state.audioPreviewer.reset();
      updateGenerateButtonState();
    });

    // Image Dropzone
    setupDropzone(el.imageDrop, el.imageInput, (file) => {
      if (!file.type.startsWith('image/')) {
        alert('이미지 파일(.jpg, .png, .webp 등)만 업로드 가능합니다.');
        return;
      }
      state.imageFile = file;
      el.imageFileName.textContent = file.name;
      el.imageFileSize.textContent = formatBytes(file.size);
      el.imageDrop.style.display = 'none';
      el.imageLoadedCard.classList.add('active');

      const url = URL.createObjectURL(file);
      el.imageThumb.src = url;

      const img = new Image();
      img.onload = () => {
        state.imageBitmap = img;
        renderLivePreview();
      };
      img.src = url;

      updateGenerateButtonState();
    });

    el.btnRemoveImage.addEventListener('click', () => {
      state.imageFile = null;
      state.imageBitmap = null;
      el.imageInput.value = '';
      el.imageLoadedCard.classList.remove('active');
      el.imageDrop.style.display = 'flex';
      el.imageThumb.src = '';
      renderLivePreview();
      updateGenerateButtonState();
    });
  }

  function setupDropzone(dropEl, inputEl, onFileSelected) {
    dropEl.addEventListener('click', () => inputEl.click());
    inputEl.addEventListener('change', () => {
      if (inputEl.files && inputEl.files[0]) {
        onFileSelected(inputEl.files[0]);
      }
    });

    ['dragenter', 'dragover'].forEach(name => {
      dropEl.addEventListener(name, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropEl.classList.add('drag-over');
      });
    });

    ['dragleave', 'drop'].forEach(name => {
      dropEl.addEventListener(name, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropEl.classList.remove('drag-over');
      });
    });

    dropEl.addEventListener('drop', (e) => {
      const files = e.dataTransfer.files;
      if (files && files[0]) {
        onFileSelected(files[0]);
      }
    });
  }

  function initModeCards() {
    el.modeCards.forEach(card => {
      card.addEventListener('click', () => {
        el.modeCards.forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        state.selectedMode = card.dataset.mode;
        updateOptionsVisibility();
        updateGenerateButtonState();
        renderLivePreview();
      });
    });

    if (el.batchToggle) {
      el.batchToggle.addEventListener('change', (e) => {
        state.batchAll = e.target.checked;
        updateOptionsVisibility();
        updateGenerateButtonState();
      });
    }
  }

  function updateOptionsVisibility() {
    const needOverlayOptions = state.batchAll || state.selectedMode === 'waveform_overlay' || state.selectedMode === 'waveform';
    if (el.optionsPanel) {
      el.optionsPanel.style.display = needOverlayOptions ? 'block' : 'none';
    }
  }

  function initCustomizerInputs() {
    el.waveColorInput.addEventListener('input', (e) => {
      applyColor(e.target.value);
    });

    el.waveColorHex.addEventListener('input', (e) => {
      let val = e.target.value.trim();
      if (!val.startsWith('#')) val = '#' + val;
      if (/^#[0-9a-fA-F]{6}$/.test(val)) {
        applyColor(val);
      }
    });

    el.opacitySlider.addEventListener('input', (e) => {
      state.opacity = parseFloat(e.target.value);
      el.opacityVal.textContent = `${Math.round(state.opacity * 100)}%`;
      renderLivePreview();
    });

    el.heightSlider.addEventListener('input', (e) => {
      state.waveHeight = parseInt(e.target.value, 10);
      el.heightVal.textContent = `${state.waveHeight}px`;
      renderLivePreview();
    });

    el.posButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        el.posButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.position = btn.dataset.pos;
        renderLivePreview();
      });
    });
  }

  function initPreviewCanvas() {
    window.addEventListener('resize', () => renderLivePreview());
    renderLivePreview();
  }

  function renderLivePreview() {
    const canvas = el.previewCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width = 1920;
    const height = canvas.height = 1080;

    // Draw Background
    if (state.imageBitmap && (state.selectedMode !== 'waveform' || state.batchAll)) {
      // Scale and center cover 16:9
      const img = state.imageBitmap;
      const imgAspect = img.width / img.height;
      const targetAspect = 16 / 9;
      let drawW, drawH, drawX, drawY;

      if (imgAspect > targetAspect) {
        drawH = height;
        drawW = height * imgAspect;
        drawX = (width - drawW) / 2;
        drawY = 0;
      } else {
        drawW = width;
        drawH = width / imgAspect;
        drawX = 0;
        drawY = (height - drawH) / 2;
      }
      ctx.drawImage(img, drawX, drawY, drawW, drawH);
    } else {
      // Default Studio Void Background
      const grad = ctx.createLinearGradient(0, 0, width, height);
      grad.addColorStop(0, '#0a0e18');
      grad.addColorStop(1, '#05070d');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, width, height);

      // Subtle grid line
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
      ctx.lineWidth = 1;
      for (let x = 0; x < width; x += 80) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
    }

    // If Static mode only, do not draw waveform
    if (state.selectedMode === 'static' && !state.batchAll) {
      return;
    }

    // Waveform Simulation
    const waveH = state.waveHeight;
    let waveY = 0;
    if (state.position === 'center') {
      waveY = (height - waveH) / 2;
    } else if (state.position === 'top') {
      waveY = 100;
    } else { // bottom
      waveY = height - waveH - 100;
    }

    ctx.save();
    ctx.globalAlpha = state.opacity;
    ctx.strokeStyle = state.waveColor;
    ctx.fillStyle = state.waveColor;
    ctx.shadowColor = state.waveColor;
    ctx.shadowBlur = 14;
    ctx.lineWidth = 3;

    // Draw stylized wave cline curve
    const centerY = waveY + waveH / 2;
    const numPoints = 240;
    ctx.beginPath();
    for (let i = 0; i <= numPoints; i++) {
      const x = (i / numPoints) * width;
      const angle = (i / 15);
      const envelope = Math.sin((i / numPoints) * Math.PI); // Windowing curve
      const amp = (Math.sin(angle * 1.8) * 0.4 + Math.cos(angle * 3.7) * 0.35 + Math.sin(angle * 5.5) * 0.25) * (waveH * 0.45) * envelope;
      const y = centerY + amp;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Secondary harmonic line for cline aesthetic
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i <= numPoints; i++) {
      const x = (i / numPoints) * width;
      const angle = (i / 15) + 0.8;
      const envelope = Math.sin((i / numPoints) * Math.PI);
      const amp = (Math.cos(angle * 2.2) * 0.5 + Math.sin(angle * 4.1) * 0.3) * (waveH * 0.3) * envelope;
      const y = centerY - amp;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    ctx.restore();
  }

  function updateGenerateButtonState() {
    if (!state.audioFile) {
      el.btnGenerate.disabled = true;
      el.btnGenerate.innerHTML = `<span>오디오 파일을 업로드하세요</span>`;
      return;
    }

    const needImage = state.batchAll || state.selectedMode === 'waveform_overlay' || state.selectedMode === 'static';
    if (needImage && !state.imageFile) {
      el.btnGenerate.disabled = true;
      el.btnGenerate.innerHTML = `<span>배경 이미지를 업로드하세요</span>`;
      return;
    }

    el.btnGenerate.disabled = false;
    let label = '비디오 렌더링 시작';
    if (state.batchAll) {
      label = '⚡ 3종 비디오 일괄 렌더링 시작';
    } else if (state.selectedMode === 'waveform') {
      label = '🎵 파형 비디오 렌더링 시작';
    } else if (state.selectedMode === 'waveform_overlay') {
      label = '🌊 웨이브 오버레이 비디오 렌더링 시작';
    } else if (state.selectedMode === 'static') {
      label = '🖼️ 정지 이미지 비디오 렌더링 시작';
    }
    el.btnGenerate.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
      <span>${label}</span>
    `;
  }

  function initLogToggle() {
    el.btnToggleLog.addEventListener('click', () => {
      const isOpen = el.terminalDrawer.classList.toggle('open');
      el.btnToggleLog.textContent = isOpen ? '로그 닫기 ▲' : 'FFmpeg 로그 보기 ▼';
    });
  }

  function initModal() {
    el.btnCloseModal.addEventListener('click', closeModal);
    el.videoModal.addEventListener('click', (e) => {
      if (e.target === el.videoModal) closeModal();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeModal();
    });
  }

  function openModal(title, url) {
    el.modalTitle.textContent = title;
    el.modalVideo.src = url;
    el.videoModal.classList.add('open');
    el.modalVideo.play().catch(() => {});
  }

  function closeModal() {
    el.modalVideo.pause();
    el.modalVideo.src = '';
    el.videoModal.classList.remove('open');
  }

  // Run Video Generation
  function initRunAction() {
    el.btnGenerate.addEventListener('click', startGeneration);
    el.btnCancel.addEventListener('click', cancelCurrentJob);
  }

  async function startGeneration() {
    if (!state.audioFile) return;

    let tasks = [];
    if (state.batchAll) {
      tasks = ['waveform', 'waveform_overlay', 'static'];
    } else {
      tasks = [state.selectedMode];
    }

    const fd = new FormData();
    fd.append('audio', state.audioFile);
    if (state.imageFile) {
      fd.append('image', state.imageFile);
    }
    fd.append('tasks', tasks.join(','));
    fd.append('wave_color', state.waveColor);
    fd.append('opacity', state.opacity);
    fd.append('wave_height', state.waveHeight);
    fd.append('position', state.position);

    // Update UI to running state
    el.btnGenerate.disabled = true;
    el.monitorPanel.classList.add('active');
    el.resultsContainer.classList.remove('active');
    el.resultsList.innerHTML = '';
    el.terminalLog.textContent = '';
    updateSteps('upload');
    updateProgress(5, '파일 업로드 중...');

    try {
      const res = await fetch('/api/run', { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '요청 실패');

      state.activeJobId = data.id;
      updateSteps('analyze');
      updateProgress(15, '오디오 신호 분석 중...');
      startPolling();
    } catch (err) {
      alert('오류: ' + err.message);
      resetMonitorUI();
    }
  }

  function startPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(pollJobStatus, 600);
  }

  async function pollJobStatus() {
    if (!state.activeJobId) return;
    try {
      const res = await fetch(`/api/status?id=${state.activeJobId}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '상태 조회 실패');

      if (data.log) {
        el.terminalLog.textContent = data.log;
        el.terminalLog.scrollTop = el.terminalLog.scrollHeight;
      }

      if (data.status === 'running') {
        updateSteps('encode');
        const pct = Math.max(20, Math.min(95, data.progress || 25));
        updateProgress(pct, `${data.current_task || 'FFmpeg 영상 렌더링 중'} (${pct}%)`);
      } else if (data.status === 'done' || data.status === 'partial') {
        clearInterval(state.pollTimer);
        updateSteps('complete');
        updateProgress(100, data.status === 'done' ? '✨ 렌더링 완료!' : '⚠️ 일부 작업 완료');
        renderResults(data.results || []);
        resetMonitorUI(false);
        fetchLibraryFiles();
      } else if (data.status === 'error' || data.status === 'cancelled') {
        clearInterval(state.pollTimer);
        updateProgress(0, data.status === 'cancelled' ? '작업 취소됨' : '렌더링 실패');
        alert((data.status === 'cancelled' ? '작업이 취소되었습니다.' : '오류 발생: ') + (data.error || '알 수 없는 오류'));
        resetMonitorUI(true);
      }
    } catch (err) {
      console.warn('Poll error:', err);
    }
  }

  async function cancelCurrentJob() {
    if (!state.activeJobId) return;
    if (!confirm('현재 실행 중인 렌더링 작업을 취소하시겠습니까?')) return;
    try {
      await fetch(`/api/cancel?id=${state.activeJobId}`, { method: 'POST' });
    } catch (e) {}
  }

  function updateProgress(percent, stageText) {
    el.progressBar.style.width = `${percent}%`;
    el.percentageText.textContent = `${percent}%`;
    el.stageBadge.innerHTML = `
      <span class="status-beacon"></span>
      <span>${stageText}</span>
    `;
  }

  function updateSteps(currentStage) {
    const stages = ['upload', 'analyze', 'encode', 'complete'];
    const curIdx = stages.indexOf(currentStage);

    el.stepPills.forEach((pill, idx) => {
      pill.classList.remove('active', 'done');
      if (idx < curIdx) {
        pill.classList.add('done');
      } else if (idx === curIdx) {
        pill.classList.add('active');
      }
    });
  }

  function resetMonitorUI(fullReset = true) {
    el.btnGenerate.disabled = false;
    updateGenerateButtonState();
    if (fullReset) {
      el.monitorPanel.classList.remove('active');
    }
  }

  function renderResults(results) {
    el.resultsList.innerHTML = '';
    if (!results || !results.length) return;

    results.forEach(item => {
      const card = document.createElement('div');
      card.className = 'result-card';
      card.innerHTML = `
        <div class="result-info">
          <h4>${item.task}</h4>
          <p>${item.url.split('/').pop()}</p>
        </div>
        <div class="result-actions">
          <button class="btn-preview-video" data-url="${item.url}" data-title="${item.task}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
            비디오 재생
          </button>
          <a href="${item.url}" download class="btn-download-video">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
            다운로드
          </a>
        </div>
      `;

      card.querySelector('.btn-preview-video').addEventListener('click', (e) => {
        openModal(item.task, item.url);
      });

      el.resultsList.appendChild(card);
    });

    el.resultsContainer.classList.add('active');
    el.resultsContainer.scrollIntoView({ behavior: 'smooth' });
  }

  // Media Library
  async function fetchLibraryFiles() {
    try {
      const res = await fetch('/api/files');
      const data = await res.json();
      if (!res.ok) return;

      el.libraryGrid.innerHTML = '';
      if (!data.files || !data.files.length) {
        el.libraryGrid.innerHTML = '<div class="empty-library-msg">생성된 비디오 파일이 아직 없습니다.</div>';
        return;
      }

      data.files.forEach(f => {
        const item = document.createElement('div');
        item.className = 'library-item';
        item.innerHTML = `
          <div class="library-item-left">
            <div class="lib-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M18 3v2h-2V3H8v2H6V3H4v18h2v-2h2v2h8v-2h2v2h2V3h-2zM8 17H6v-2h2v2zm0-4H6v-2h2v2zm0-4H6V7h2v2zm10 8h-2v-2h2v2zm0-4h-2v-2h2v2zm0-4h-2V7h2v2z"/></svg>
            </div>
            <div class="lib-meta">
              <h5 title="${f.name}">${f.name}</h5>
              <p>${f.formatted_size || formatBytes(f.size)} • ${f.created_time || ''}</p>
            </div>
          </div>
          <div class="library-item-actions">
            <button class="btn-lib-action btn-play" title="미리보기">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
              재생
            </button>
            <a href="${f.url}" download class="btn-lib-action" title="다운로드">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
              다운로드
            </a>
            <button class="btn-lib-action btn-del" title="삭제">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
            </button>
          </div>
        `;

        item.querySelector('.btn-play').addEventListener('click', () => {
          openModal(f.name, f.url);
        });

        item.querySelector('.btn-del').addEventListener('click', async () => {
          if (!confirm(`'${f.name}' 파일을 삭제하시겠습니까?`)) return;
          try {
            await fetch(`/api/files/${encodeURIComponent(f.name)}`, { method: 'DELETE' });
            fetchLibraryFiles();
          } catch (e) {
            alert('삭제 실패: ' + e.message);
          }
        });

        el.libraryGrid.appendChild(item);
      });
    } catch (e) {
      console.warn('Library load failed:', e);
    }
  }

  function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

})();
