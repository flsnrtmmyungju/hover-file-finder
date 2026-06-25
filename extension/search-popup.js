const SERVER = 'http://localhost:7823';
const id = parseInt(new URLSearchParams(location.search).get('id'));

// ── 탭 전환 ────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');

    if (btn.dataset.tab === 'history')  loadHistory();
    if (btn.dataset.tab === 'finished') loadStatus('다읽음', 'finishedList');
    if (btn.dataset.tab === 'giveup')   loadStatus('포기',   'giveupList');
  });
});

// ── 뷰어 열기 ──────────────────────────────────────────────────
function openViewer(filename) {
  chrome.runtime.sendMessage({ type: 'open-viewer', filename });
}

// ── 검색 탭 ────────────────────────────────────────────────────
function renderSearch(data) {
  document.getElementById('queryText').textContent = data.text || '';
  const container = document.getElementById('results');
  const exact   = data.exact   || [];
  const partial = data.partial || [];

  if (exact.length === 0 && partial.length === 0) {
    container.innerHTML = '<div class="empty">일치하는 파일 없음</div>';
    return;
  }

  function makeItem(item, cls) {
    const d = document.createElement('div');
    d.className = 'item ' + cls;
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = item.name;
    name.title = item.name;
    const size = document.createElement('span');
    size.className = 'size';
    size.textContent = item.size ? item.size + ' MB' : '';
    d.appendChild(name);
    d.appendChild(size);
    return d;
  }

  if (exact.length > 0) {
    const t = document.createElement('div');
    t.className = 'section-title';
    t.textContent = '정확 일치 ' + exact.length + '개';
    container.appendChild(t);
    exact.forEach(item => container.appendChild(makeItem(item, 'exact')));
  }
  if (partial.length > 0) {
    const t = document.createElement('div');
    t.className = 'section-title';
    t.textContent = '부분 일치 ' + partial.length + '개';
    container.appendChild(t);
    partial.forEach(item => container.appendChild(makeItem(item, 'partial')));
  }
}

chrome.storage.session.get(String(id), (res) => {
  const data = res[String(id)];
  if (data) renderSearch(data);
  else document.getElementById('results').innerHTML = '<div class="empty">결과를 불러올 수 없음</div>';
});

// ── 읽은기록 탭 ────────────────────────────────────────────────
function loadHistory() {
  const container = document.getElementById('historyList');
  container.innerHTML = '<div class="empty">불러오는 중...</div>';

  Promise.all([
    fetch(`${SERVER}/history`).then(r => r.json()),
    fetch(`${SERVER}/reading-status`).then(r => r.json()),
  ]).then(([hist, statusMap]) => {
    // 포기/다읽음 제외
    const filtered = hist.filter(h => {
      const s = statusMap[h.filename];
      return !s || (s.status !== '포기' && s.status !== '다읽음');
    });

    container.innerHTML = '';
    if (filtered.length === 0) {
      container.innerHTML = '<div class="empty">기록 없음</div>';
      return;
    }

    filtered.forEach(h => {
      const row = document.createElement('div');
      row.className = 'rec-item';

      const name = document.createElement('span');
      name.className = 'rec-name';
      name.textContent = h.filename;
      name.title = h.filename;

      const meta = document.createElement('span');
      meta.className = 'rec-meta';
      meta.textContent = (h.opened_at || '').slice(0, 10);

      const pos = document.createElement('span');
      pos.className = 'rec-pos';
      pos.textContent = h.position > 0 ? h.position.toFixed(0) + '%' : '';

      const del = document.createElement('button');
      del.className = 'del-btn';
      del.textContent = '✕';
      del.title = '기록 삭제';
      del.addEventListener('click', (e) => {
        e.stopPropagation();
        fetch(`${SERVER}/history/delete`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: h.filename })
        }).then(() => { row.remove(); });
      });

      row.appendChild(name);
      row.appendChild(meta);
      row.appendChild(pos);
      row.appendChild(del);
      row.addEventListener('click', () => openViewer(h.filename));
      container.appendChild(row);
    });
  }).catch(() => {
    container.innerHTML = '<div class="empty">불러오기 실패</div>';
  });
}

// ── 다읽음 / 포기 탭 ───────────────────────────────────────────
function loadStatus(statusFilter, containerId) {
  const container = document.getElementById(containerId);
  container.innerHTML = '<div class="empty">불러오는 중...</div>';

  fetch(`${SERVER}/reading-status`)
    .then(r => r.json())
    .then(all => {
      const entries = Object.entries(all)
        .filter(([, v]) => v.status === statusFilter)
        .sort((a, b) => (b[1].ts || 0) - (a[1].ts || 0));

      container.innerHTML = '';
      if (entries.length === 0) {
        container.innerHTML = `<div class="empty">${statusFilter} 목록 없음</div>`;
        return;
      }

      entries.forEach(([fname, info]) => {
        const row = document.createElement('div');
        row.className = 'rec-item';

        const name = document.createElement('span');
        name.className = 'rec-name';
        name.textContent = fname;
        name.title = fname;

        const meta = document.createElement('span');
        meta.className = 'rec-meta';
        meta.textContent = info.date || '';

        const del = document.createElement('button');
        del.className = 'del-btn';
        del.textContent = '✕';
        del.title = '목록에서 제거';
        del.addEventListener('click', (e) => {
          e.stopPropagation();
          fetch(`${SERVER}/reading-status?filename=${encodeURIComponent(fname)}`, { method: 'DELETE' })
            .then(() => { row.remove(); });
        });

        row.appendChild(name);
        row.appendChild(meta);
        row.appendChild(del);
        row.addEventListener('click', () => openViewer(fname));
        container.appendChild(row);
      });
    }).catch(() => {
      container.innerHTML = '<div class="empty">불러오기 실패</div>';
    });
}

// ── 닫기 ───────────────────────────────────────────────────────
document.getElementById('closeBtn').addEventListener('click', () => window.close());
document.addEventListener('keydown', e => { if (e.key === 'Escape') window.close(); });
