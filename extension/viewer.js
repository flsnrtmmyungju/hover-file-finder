const SERVER = 'http://localhost:7823';
const params = new URLSearchParams(location.search);
const filename = params.get('filename') || '';

const contentEl = document.getElementById('content');

// 창 위치·크기 저장
let boundsTimer = null;
function saveWindowBounds() {
  chrome.storage.local.set({ viewer_window: {
    left:   window.screenX,
    top:    window.screenY,
    width:  window.outerWidth,
    height: window.outerHeight,
  }});
}
window.addEventListener('resize', () => {
  clearTimeout(boundsTimer);
  boundsTimer = setTimeout(saveWindowBounds, 600);
});
window.addEventListener('beforeunload', saveWindowBounds);

// ── 통합 저장 (위치 + 상태) ─────────────────────────────────────

function getScrollPct() {
  const max = contentEl.scrollHeight - contentEl.clientHeight;
  return max > 0 ? Math.round(contentEl.scrollTop / max * 1000) / 10 : 0;
}

function savePosition() {
  if (!filename) return;
  fetch(`${SERVER}/novel-data`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename, position: getScrollPct() })
  }).catch(() => {});
}

function saveStatus(status) {
  if (!filename) return;
  return fetch(`${SERVER}/novel-data`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename, status, position: getScrollPct() })
  });
}

// 현재 파일 저장정보 로드
if (filename) {
  fetch(`${SERVER}/novel-data`)
    .then(r => r.json())
    .then(all => {
      const entry = all[filename];
      if (entry && entry.status) {
        document.getElementById('statusSelect').value = entry.status;
      }
    })
    .catch(() => {});
}

// 상태저장 버튼
const saveStatusBtn = document.getElementById('saveStatusBtn');
let statusFeedbackTimer = null;
saveStatusBtn.addEventListener('click', () => {
  const status = document.getElementById('statusSelect').value;
  saveStatus(status).then(() => {
    saveStatusBtn.classList.add('saved');
    clearTimeout(statusFeedbackTimer);
    statusFeedbackTimer = setTimeout(() => saveStatusBtn.classList.remove('saved'), 1500);
  }).catch(() => {});
});

// 위치저장 버튼
const savePosBtn = document.getElementById('savePosBtn');
let posFeedbackTimer = null;
savePosBtn.addEventListener('click', () => {
  savePosition();
  savePosBtn.classList.add('saved');
  clearTimeout(posFeedbackTimer);
  posFeedbackTimer = setTimeout(() => savePosBtn.classList.remove('saved'), 1500);
});

// ── 스타일 설정 ────────────────────────────────────────────────

const DEFAULTS = {
  padding:    12,
  font:       "'Malgun Gothic','Nanum Gothic',sans-serif",
  fontSize:   15,
  lineHeight: 2.0,
  bg:         '#1e1e2e',
  fg:         '#cdd6f4',
};
const LS_KEY = 'viewer_style';

function loadStyle() {
  try {
    const saved = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
    return Object.assign({}, DEFAULTS, saved);
  } catch { return { ...DEFAULTS }; }
}

function saveStyle(st) {
  localStorage.setItem(LS_KEY, JSON.stringify(st));
}

function hexLuminance(hex) {
  const r = parseInt(hex.slice(1,3),16)/255;
  const g = parseInt(hex.slice(3,5),16)/255;
  const b = parseInt(hex.slice(5,7),16)/255;
  return 0.299*r + 0.587*g + 0.114*b;
}

function applyStyle(st) {
  contentEl.style.padding    = `28px ${st.padding}%`;
  contentEl.style.fontFamily = st.font;
  contentEl.style.fontSize   = st.fontSize + 'px';
  contentEl.style.lineHeight = st.lineHeight;
  document.body.style.background = st.bg;
  contentEl.style.color      = st.fg;

  const root = document.documentElement;
  root.style.setProperty('--sb-track', st.bg);
  if (hexLuminance(st.bg) < 0.5) {
    root.style.setProperty('--sb-thumb',       'rgba(255,255,255,0.13)');
    root.style.setProperty('--sb-thumb-hover', 'rgba(255,255,255,0.25)');
  } else {
    root.style.setProperty('--sb-thumb',       'rgba(0,0,0,0.15)');
    root.style.setProperty('--sb-thumb-hover', 'rgba(0,0,0,0.30)');
  }
}

function syncUI(st) {
  document.getElementById('sPadding').value    = st.padding;
  document.getElementById('sFontSize').value   = st.fontSize;
  document.getElementById('sLineHeight').value = st.lineHeight;
  document.getElementById('sBg').value         = st.bg;
  document.getElementById('sFg').value         = st.fg;
  document.getElementById('vPadding').textContent    = st.padding + '%';
  document.getElementById('vFontSize').textContent   = st.fontSize + 'px';
  document.getElementById('vLineHeight').textContent = parseFloat(st.lineHeight).toFixed(1);
  const sel = document.getElementById('sFont');
  for (const opt of sel.options) {
    if (opt.value === st.font) { sel.value = st.font; break; }
  }
}

let curStyle = loadStyle();
applyStyle(curStyle);

(function initSettings() {
  syncUI(curStyle);
  const panel = document.getElementById('settingsPanel');
  const btn   = document.getElementById('settingsBtn');
  btn.addEventListener('click', () => {
    const open = panel.classList.toggle('open');
    btn.classList.toggle('active', open);
  });
  function onChange() {
    curStyle = {
      padding:    parseInt(document.getElementById('sPadding').value),
      font:       document.getElementById('sFont').value,
      fontSize:   parseInt(document.getElementById('sFontSize').value),
      lineHeight: parseFloat(document.getElementById('sLineHeight').value),
      bg:         document.getElementById('sBg').value,
      fg:         document.getElementById('sFg').value,
    };
    document.getElementById('vPadding').textContent    = curStyle.padding + '%';
    document.getElementById('vFontSize').textContent   = curStyle.fontSize + 'px';
    document.getElementById('vLineHeight').textContent = curStyle.lineHeight.toFixed(1);
    applyStyle(curStyle);
    saveStyle(curStyle);
  }
  ['sPadding','sFont','sFontSize','sLineHeight','sBg','sFg'].forEach(id => {
    document.getElementById(id).addEventListener('input', onChange);
  });
  document.getElementById('resetBtn').addEventListener('click', () => {
    curStyle = { ...DEFAULTS };
    syncUI(curStyle);
    applyStyle(curStyle);
    saveStyle(curStyle);
  });
})();

// ── 확인 모달 ──────────────────────────────────────────────────

function showConfirm(msg, onOk, onCancel) {
  const overlay = document.getElementById('confirmOverlay');
  document.getElementById('confirmMsg').textContent = msg;
  overlay.classList.add('open');
  const ok     = document.getElementById('confirmOk');
  const cancel = document.getElementById('confirmCancel');
  const newOk     = ok.cloneNode(true);
  const newCancel = cancel.cloneNode(true);
  ok.replaceWith(newOk);
  cancel.replaceWith(newCancel);
  const close = () => overlay.classList.remove('open');
  newOk.addEventListener('click',     () => { close(); onOk && onOk(); });
  newCancel.addEventListener('click', () => { close(); onCancel && onCancel(); });
}

// ── 뷰어 본체 ──────────────────────────────────────────────────

function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const CH_RE = /^(?:제\s*\d+\s*화|#\s*\d+|\d+\s*화|chapter\s*\d+|\[\d+화?\])/i;

document.title = filename.replace(/\.txt$/i, '');
document.getElementById('title').textContent = filename.replace(/\.txt$/i, '');

fetch(`${SERVER}/view?filename=${encodeURIComponent(filename)}`)
  .then(r => {
    if (r.status === 404) return r.json().then(j => { throw Object.assign(new Error(j.error || '파일 없음'), { notFound: true }); });
    return r.json();
  })
  .then(data => {
    document.getElementById('loading').remove();
    contentEl.style.display = 'block';
    applyStyle(curStyle);

    const lines = (data.content || '').split('\n');
    const chapters = [];
    let html = '';
    let chIdx = 0;

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed && CH_RE.test(trimmed)) {
        const id = 'ch' + chIdx++;
        chapters.push({ id, title: trimmed });
        html += `<span class="ch" id="${id}">${esc(line)}</span>`;
      } else {
        html += esc(line) + '\n';
      }
    }

    contentEl.innerHTML = html;

    if (chapters.length > 0) {
      const sel = document.getElementById('chapterSelect');
      sel.style.display = 'block';
      chapters.forEach(ch => {
        const opt = document.createElement('option');
        opt.value = ch.id;
        opt.textContent = ch.title.slice(0, 30);
        sel.appendChild(opt);
      });
      sel.addEventListener('change', () => {
        document.getElementById(sel.value)?.scrollIntoView({ behavior: 'smooth' });
      });
      const anchors = chapters.map(ch => document.getElementById(ch.id));
      contentEl.addEventListener('scroll', () => {
        const top = contentEl.scrollTop + 60;
        let cur = 0;
        for (let i = 0; i < anchors.length; i++) {
          if (anchors[i] && anchors[i].offsetTop <= top) cur = i;
        }
        sel.selectedIndex = cur;
      }, { passive: true });
    }

    // 저장된 위치 복원
    fetch(`${SERVER}/novel-data`)
      .then(r => r.json())
      .then(all => {
        const entry = all[filename];
        if (entry) {
          if (entry.status) document.getElementById('statusSelect').value = entry.status;
          if (entry.position > 0) {
            setTimeout(() => {
              const max = contentEl.scrollHeight - contentEl.clientHeight;
              contentEl.scrollTop = max * entry.position / 100;
            }, 100);
          }
        }
      }).catch(() => {});

    contentEl.addEventListener('scroll', () => {
      document.getElementById('posInfo').textContent = getScrollPct().toFixed(0) + '%';
    }, { passive: true });

  })
  .catch(err => {
    const loadingEl = document.getElementById('loading');
    if (err.notFound && filename) {
      loadingEl.textContent = '파일이 삭제되었습니다.';
      showConfirm('기록에서도 제거할까요?', () => {
        fetch(`${SERVER}/novel-data?filename=${encodeURIComponent(filename)}`, { method: 'DELETE' })
          .catch(() => {});
        loadingEl.textContent = '기록에서 제거했습니다.';
      });
    } else {
      loadingEl.textContent = '파일 로드 실패';
    }
  });
