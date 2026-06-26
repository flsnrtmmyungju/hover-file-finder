const id = parseInt(new URLSearchParams(location.search).get('id'));
const input = document.getElementById('nameInput');
const convertBtn = document.getElementById('convertBtn');
const copyBtn = document.getElementById('copyBtn');
copyBtn.addEventListener('click', () => {
  const v = input.value.trim();
  if (!v) return;
  navigator.clipboard.writeText(v).then(() => {
    copyBtn.textContent = '✓';
    setTimeout(() => { copyBtn.textContent = '⎘'; }, 1200);
  });
});

function applyData(data) {
  if (!data) return;
  const orig = data.original || '';
  const name = data.cleaned || orig;
  document.getElementById('orig').textContent = orig;
  document.getElementById('orig').title = orig;
  input.value = name;
  input.focus();
  const dot = name.lastIndexOf('.');
  input.setSelectionRange(0, dot > 0 ? dot : name.length);
  // epub이면 변환 버튼 표시, okBtn 레이블 변경
  if (orig.toLowerCase().endsWith('.epub')) {
    convertBtn.style.display = 'block';
  } else {
    document.getElementById('okBtn').textContent = '저장';
  }
}

chrome.storage.session.get(String(id), (res) => {
  if (res && res[String(id)]) applyData(res[String(id)]);
});

chrome.runtime.sendMessage({ type: 'ready', id }, (data) => {
  if (chrome.runtime.lastError) return;
  if (data) applyData(data);
});

document.getElementById('okBtn').addEventListener('click', () => {
  const v = input.value.trim();
  if (v) chrome.runtime.sendMessage({ type: 'confirm', id, name: v });
});

convertBtn.addEventListener('click', () => {
  const v = input.value.trim();
  if (v) chrome.runtime.sendMessage({ type: 'confirm', id, name: v, convertEpub: true });
});

document.getElementById('cancelBtn').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'cancel', id });
});

input.addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('okBtn').click();
  if (e.key === 'Escape') document.getElementById('cancelBtn').click();
});
