// MAIN world content.js → ISOLATED world → background.js 중계
window.addEventListener('message', (e) => {
  if (e.source !== window || !e.data || e.data.type !== 'kiwi-search') return;
  chrome.runtime.sendMessage({ type: 'kiwi-search', text: e.data.text });
});
