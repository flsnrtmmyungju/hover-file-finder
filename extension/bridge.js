window.addEventListener('message', (e) => {
  if (e.source !== window || !e.data?.type) return;
  if (e.data.type === 'open-viewer') {
    chrome.runtime.sendMessage({ type: 'open-viewer', filename: e.data.filename });
  }
});
