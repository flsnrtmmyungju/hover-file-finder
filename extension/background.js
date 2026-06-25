const pendingCallbacks = new Map(); // id → { suggest, dir, original, downloadId, windowId }
const epubConvertQueue = new Map(); // downloadId → filename

function cancelEntry(id) {
  const entry = pendingCallbacks.get(id);
  if (!entry) return;
  // 다운로드 취소 후 suggest는 dummy로 호출 (Chrome이 대기 해제)
  chrome.downloads.cancel(entry.downloadId, () => {
    try { entry.suggest({ filename: entry.dir + entry.original }); } catch {}
  });
  pendingCallbacks.delete(id);
  chrome.storage.session.remove(String(id));
}

chrome.downloads.onDeterminingFilename.addListener((item, suggest) => {
  const full = item.filename;
  const basename = full.replace(/.*[\\/]/, '');
  const ext = (basename.match(/\.[^.]+$/) || [''])[0].toLowerCase();
  if (ext !== '.txt' && ext !== '.zip' && ext !== '.epub') return;

  const id = Date.now();

  fetch(`http://localhost:7823/clean-name?name=${encodeURIComponent(basename)}`)
    .then(r => r.json())
    .then(d => {
      const cleaned = d.cleaned ? d.cleaned + ext : basename;
      const dir = full.slice(0, full.length - basename.length);

      pendingCallbacks.set(id, { suggest, dir, original: basename, downloadId: item.id });
      chrome.storage.session.set({ [id]: { original: basename, cleaned } });

      chrome.windows.getLastFocused({ populate: false }, (win) => {
        const pw = 640, ph = 200;
        const left = win ? Math.round(win.left + (win.width - pw) / 2) : 600;
        const top  = win ? Math.round(win.top  + (win.height - ph) / 2) : 400;
        const url = chrome.runtime.getURL('dialog.html') + '?id=' + id;
        chrome.windows.create({ url, type: 'popup', width: pw, height: ph, left, top, focused: true });
      });
    })
    .catch(() => suggest({ filename: full }));

  return true;
});

// epub 변환: 다운로드 완료 감지 → 서버에 변환 요청
chrome.downloads.onChanged.addListener((delta) => {
  if (delta.state && delta.state.current === 'complete') {
    const filename = epubConvertQueue.get(delta.id);
    if (filename) {
      epubConvertQueue.delete(delta.id);
      fetch(`http://localhost:7823/epub-convert?filename=${encodeURIComponent(filename)}`, { method: 'POST' })
        .then(r => r.json())
        .then(d => {
          if (d.error === 'calibre 미설치') {
            chrome.notifications.create({
              type: 'basic', iconUrl: 'icon.png',
              title: 'Calibre 미설치',
              message: `설치 필요: ${d.install}`
            });
          }
        })
        .catch(() => {});
    }
  }
});

// 창 X 버튼으로 닫으면 → 다운로드 취소
chrome.windows.onRemoved.addListener((windowId) => {
  for (const [id, entry] of pendingCallbacks) {
    if (entry.windowId === windowId) {
      cancelEntry(id);
    }
  }
});

function openSearchPopup(id) {
  chrome.windows.getLastFocused({ populate: false }, (win) => {
    const pw = 580, ph = 420;
    const left = win ? Math.round(win.left + (win.width - pw) / 2) : 500;
    const top  = win ? Math.round(win.top  + (win.height - ph) / 2) : 300;
    chrome.windows.create({
      url: chrome.runtime.getURL('search-popup.html') + '?id=' + id,
      type: 'popup', width: pw, height: ph, left, top, focused: true
    });
  });
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const id = msg.id;

  if (msg.type === 'kiwi-search') {
    fetch(`http://localhost:7823/search?text=${encodeURIComponent(msg.text)}`)
      .then(r => r.json())
      .then(data => {
        const sid = Date.now();
        chrome.storage.session.set({
          [sid]: {
            text: msg.text,
            exact: data.exact || [],
            partial: data.partial || []
          }
        });
        openSearchPopup(sid);
      })
      .catch(() => {});
    return true;
  }

  if (msg.type === 'ready') {
    const entry = pendingCallbacks.get(id);
    if (entry) entry.windowId = sender.tab.windowId;
    chrome.storage.session.get(String(id), (res) => {
      sendResponse(res[String(id)] || null);
    });
    return true;
  }

  if (msg.type === 'confirm') {
    const entry = pendingCallbacks.get(id);
    if (entry) {
      entry.suggest({ filename: entry.dir + msg.name });
      if (msg.convertEpub) {
        epubConvertQueue.set(entry.downloadId, msg.name);
      }
      pendingCallbacks.delete(id);
      chrome.storage.session.remove(String(id));
    }
    chrome.windows.remove(sender.tab.windowId);
  }

  if (msg.type === 'cancel') {
    cancelEntry(id);
    chrome.windows.remove(sender.tab.windowId);
  }

  if (msg.type === 'open-viewer') {
    const url = chrome.runtime.getURL('viewer.html') + '?filename=' + encodeURIComponent(msg.filename);
    chrome.storage.local.get('viewer_window', (res) => {
      const saved = res.viewer_window;
      if (saved) {
        chrome.windows.create({ url, type: 'popup', width: saved.width, height: saved.height, left: saved.left, top: saved.top, focused: true });
      } else {
        chrome.windows.getLastFocused({ populate: false }, (win) => {
          const pw = 900, ph = 700;
          const left = win ? Math.round(win.left + (win.width - pw) / 2) : 200;
          const top  = win ? Math.round(win.top  + (win.height - ph) / 2) : 100;
          chrome.windows.create({ url, type: 'popup', width: pw, height: ph, left, top, focused: true });
        });
      }
    });
  }
});
