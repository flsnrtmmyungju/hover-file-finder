(function () {
  "use strict";


  const SERVER = "http://localhost:7823/search";
  const DEBOUNCE_MS = 400;
  const MIN_TEXT_LEN = 3;
  const OVERLAY_ID = "__fhf_overlay__";

  let overlay = null;
  let timer = null;
  let hideTimer = null;
  let lastText = "";
  let mouseX = 0;
  let mouseY = 0;
  let dedupActive = false;
  let overlayHovered = false;

  function buildOverlay() {
    const el = document.createElement("div");
    el.id = OVERLAY_ID;
    Object.assign(el.style, {
      position: "fixed",
      zIndex: "2147483647",
      background: "#1e1e2e",
      color: "#cdd6f4",
      border: "1px solid #45475a",
      borderRadius: "8px",
      padding: "8px 12px",
      fontFamily: "'Segoe UI', system-ui, sans-serif",
      fontSize: "13px",
      lineHeight: "1.5",
      width: "max-content",
      maxWidth: "90vw",
      maxHeight: "280px",
      overflowY: "auto",
      boxShadow: "0 6px 24px rgba(0,0,0,.7)",
      display: "none",
      pointerEvents: "auto",
      userSelect: "none",
      left: "0px",
      top: "0px",
      boxSizing: "border-box",
    });
    el.addEventListener("mouseenter", () => { overlayHovered = true; clearTimeout(hideTimer); });
    el.addEventListener("mouseleave", () => { overlayHovered = false; });
    document.body.appendChild(el);
    return el;
  }

  function getOverlay() {
    if (!overlay || !document.body.contains(overlay)) {
      overlay = buildOverlay();
    }
    return overlay;
  }

  function makeRow(item, isExact) {
    const name = typeof item === "object" ? item.name : item;
    const size = typeof item === "object" ? item.size : null;
    const row = document.createElement("div");
    Object.assign(row.style, {
      display: "flex",
      alignItems: "center",
      padding: "4px 6px",
      borderTop: "1px solid #313244",
      fontSize: "12px",
      background: isExact ? "#a6e3a1" : "transparent",
      borderRadius: isExact ? "4px" : "0",
      marginBottom: isExact ? "2px" : "0",
      gap: "6px",
    });

    const label = document.createElement("span");
    Object.assign(label.style, {
      flex: "1",
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis",
      color: isExact ? "#1e1e2e" : "#cdd6f4",
    });
    label.title = name;
    label.textContent = name;

    // 용량 표시
    if (size !== null) {
      const sizeEl = document.createElement("span");
      Object.assign(sizeEl.style, {
        flexShrink: "0", fontSize: "10px",
        color: isExact ? "#2d6a4f" : "#6c7086",
        whiteSpace: "nowrap",
      });
      sizeEl.textContent = `${size}MB`;
      row.appendChild(sizeEl);
    }

    // 수정 버튼
    const editBtn = document.createElement("span");
    editBtn.textContent = "✏";
    Object.assign(editBtn.style, {
      cursor: "pointer", flexShrink: "0",
      opacity: isExact ? "0.7" : "0.5", fontSize: "12px",
      filter: isExact ? "brightness(0.3)" : "none",
    });
    editBtn.title = "이름 수정";
    editBtn.addEventListener("mouseenter", () => { editBtn.style.opacity = "1"; editBtn.style.filter = "none"; });
    editBtn.addEventListener("mouseleave", () => { editBtn.style.opacity = isExact ? "0.7" : "0.5"; editBtn.style.filter = isExact ? "brightness(0.3)" : "none"; });
    editBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const ext = name.includes(".") ? name.slice(name.lastIndexOf(".")) : "";
      const stem = ext ? name.slice(0, name.lastIndexOf(".")) : name;
      const input = document.createElement("input");
      Object.assign(input.style, {
        flex: "1", background: "#313244", color: "#cdd6f4",
        border: "1px solid #89b4fa", borderRadius: "3px",
        fontSize: "12px", padding: "1px 4px", outline: "none", minWidth: "0",
      });
      input.value = stem;
      label.replaceWith(input);
      input.focus();
      input.select();

      let committed = false;

      async function commit() {
        if (committed) return;
        committed = true;
        const newStem = input.value.trim();
        if (!newStem || newStem + ext === name) { input.replaceWith(label); return; }
        const newName = newStem + ext;
        try {
          const res = await fetch(
            `http://localhost:7823/rename-file?old=${encodeURIComponent(name)}&new=${encodeURIComponent(newName)}`,
            { method: "POST" }
          );
          const data = await res.json();
          if (data.ok) { label.textContent = newName; label.title = newName; }
          else { alert("실패: " + (data.error || "오류")); committed = false; }
        } catch { alert("서버 오류"); committed = false; }
        input.replaceWith(label);
      }

      input.addEventListener("keydown", (e) => {
        e.stopPropagation();
        if (e.key === "Enter") { e.preventDefault(); commit(); }
        if (e.key === "Escape") { committed = true; input.replaceWith(label); }
      });
      input.addEventListener("blur", () => { if (!committed) commit(); });
    });

    const delBtn = document.createElement("span");
    delBtn.textContent = "🗑";
    Object.assign(delBtn.style, {
      cursor: "pointer",
      flexShrink: "0",
      opacity: isExact ? "0.7" : "0.5",
      fontSize: "13px",
      filter: isExact ? "brightness(0.3)" : "none",
    });
    delBtn.title = "삭제";
    delBtn.addEventListener("mouseenter", () => { delBtn.style.opacity = "1"; delBtn.style.filter = "none"; });
    delBtn.addEventListener("mouseleave", () => { delBtn.style.opacity = isExact ? "0.7" : "0.5"; delBtn.style.filter = isExact ? "brightness(0.3)" : "none"; });
    delBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`"${name}"\n이 파일을 삭제하시겠습니까?`)) return;
      try {
        const res = await fetch(
          `http://localhost:7823/delete?filename=${encodeURIComponent(name)}`,
          { method: "POST" }
        );
        const data = await res.json();
        if (data.ok) {
          row.style.opacity = "0.3";
          row.style.textDecoration = "line-through";
          label.textContent = `✓ 삭제됨: ${name}`;
          delBtn.remove();
        } else {
          alert("삭제 실패: " + (data.error || "알 수 없는 오류"));
        }
      } catch {
        alert("서버 오류");
      }
    });

    row.appendChild(label);
    row.appendChild(editBtn);
    row.appendChild(delBtn);
    return row;
  }

  function makeActionBtn(label, color, url, onResult) {
    const btn = document.createElement("button");
    btn.textContent = label;
    Object.assign(btn.style, {
      flex: "1",
      padding: "5px 0",
      background: color,
      color: "#1e1e2e",
      border: "none",
      borderRadius: "5px",
      fontWeight: "700",
      fontSize: "11px",
      cursor: "pointer",
    });
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const orig = btn.textContent;
      btn.textContent = "처리 중...";
      btn.disabled = true;
      try {
        const res = await fetch(url, { method: "POST" });
        const data = await res.json();
        btn.textContent = onResult(data);
      // 이름정리/이동 후 팝업 내용이 구식이 되므로 닫기
      if (url.includes("rename") || url.includes("organize")) {
        setTimeout(() => { hide(true); lastText = ""; }, 1500);
      }
      } catch {
        btn.textContent = "오류";
      }
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2500);
    });
    return btn;
  }

  function makeTopButtons() {
    const wrap = document.createElement("div");
    Object.assign(wrap.style, {
      display: "flex",
      gap: "6px",
      marginBottom: "8px",
    });
    wrap.appendChild(makeActionBtn(
      "이름정리", "#89dceb",
      "http://localhost:7823/rename",
      (d) => d.error ? "오류" : `✓ ${d.renamed}개 이름변경`
    ));
    wrap.appendChild(makeActionBtn(
      "파일이동", "#cba6f7",
      "http://localhost:7823/organize",
      (d) => d.error ? "오류" : `✓ ${d.moved}개 이동`
    ));
    // 중복삭제 버튼 - 컨펌 UI
    const dedupBtn = document.createElement("button");
    dedupBtn.textContent = "중복삭제";
    Object.assign(dedupBtn.style, {
      flex: "1", padding: "5px 0", background: "#f38ba8",
      color: "#1e1e2e", border: "none", borderRadius: "5px",
      fontWeight: "700", fontSize: "11px", cursor: "pointer",
    });
    dedupBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      dedupBtn.textContent = "스캔 중...";
      dedupBtn.disabled = true;
      try {
        const res = await fetch("http://localhost:7823/deduplicate-scan", { method: "POST" });
        const data = await res.json();
        if (data.error) { dedupBtn.textContent = "오류"; return; }
        if (data.total === 0) { dedupBtn.textContent = "중복 없음"; return; }
        startDedupFlow(data.items, dedupBtn);
      } catch {
        dedupBtn.textContent = "오류";
      }
      setTimeout(() => { dedupBtn.textContent = "중복삭제"; dedupBtn.disabled = false; }, 3000);
    });
    wrap.appendChild(dedupBtn);
    return wrap;
  }

  function startDedupFlow(items, triggerBtn) {
    dedupActive = true;
    triggerBtn.disabled = true;
    let idx = 0;
    let deletedCount = 0;
    const el = getOverlay();

    function closeDedup() {
      dedupActive = false;
      triggerBtn.textContent = "중복삭제";
      triggerBtn.disabled = false;
      hide();
    }

    // ESC 키로 닫기
    const escHandler = (e) => {
      if (e.key === "Escape") { closeDedup(); document.removeEventListener("keydown", escHandler); }
    };
    document.addEventListener("keydown", escHandler);

    function renderItem() {
      if (idx >= items.length) {
        el.innerHTML = "";
        const done = document.createElement("div");
        Object.assign(done.style, { color: "#a6e3a1", fontWeight: "700", padding: "8px 0" });
        done.textContent = `✓ 완료: ${deletedCount}개 삭제됨`;
        el.appendChild(done);
        triggerBtn.textContent = `✓ ${deletedCount}개 삭제`;
        dedupActive = false;
        document.removeEventListener("keydown", escHandler);
        setTimeout(() => {
          triggerBtn.textContent = "중복삭제";
          triggerBtn.disabled = false;
        }, 3000);
        return;
      }

      const item = items[idx];
      el.innerHTML = "";

      // 헤더 행 (진행상황 + X 닫기 버튼)
      const headerRow = document.createElement("div");
      Object.assign(headerRow.style, { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" });

      const prog = document.createElement("div");
      Object.assign(prog.style, { color: "#89b4fa", fontWeight: "700", fontSize: "11px" });
      prog.textContent = `중복 확인 ${idx + 1} / ${items.length}`;

      const closeBtn = document.createElement("span");
      closeBtn.textContent = "✕";
      Object.assign(closeBtn.style, { cursor: "pointer", color: "#6c7086", fontSize: "14px", lineHeight: "1" });
      closeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        document.removeEventListener("keydown", escHandler);
        closeDedup();
      });

      headerRow.appendChild(prog);
      headerRow.appendChild(closeBtn);
      el.appendChild(headerRow);

      // 삭제될 파일
      const delRow = document.createElement("div");
      Object.assign(delRow.style, { marginBottom: "4px", fontSize: "12px" });
      delRow.innerHTML = `<span style="color:#f38ba8">🗑 삭제</span> <span style="color:#f38ba8">[${item.delete_loc}]</span> ${item.delete_name}`;
      el.appendChild(delRow);

      // 유지될 파일
      const keepRow = document.createElement("div");
      Object.assign(keepRow.style, { marginBottom: "6px", fontSize: "12px" });
      keepRow.innerHTML = `<span style="color:#a6e3a1">✓ 유지</span> <span style="color:#a6e3a1">[${item.keep_loc}]</span> ${item.keep_name}`;
      el.appendChild(keepRow);

      // 이유
      const reason = document.createElement("div");
      Object.assign(reason.style, { color: "#6c7086", fontSize: "11px", marginBottom: "10px" });
      reason.textContent = item.reason;
      el.appendChild(reason);

      // 버튼 행
      const btnRow = document.createElement("div");
      Object.assign(btnRow.style, { display: "flex", gap: "6px" });

      const confirmBtn = document.createElement("button");
      confirmBtn.textContent = "삭제";
      Object.assign(confirmBtn.style, {
        flex: "1", padding: "5px 0", background: "#f38ba8",
        color: "#1e1e2e", border: "none", borderRadius: "4px",
        fontWeight: "700", fontSize: "12px", cursor: "pointer",
      });
      confirmBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        confirmBtn.disabled = true;
        try {
          const r = await fetch(
            `http://localhost:7823/delete-path?path=${encodeURIComponent(item.delete_path)}`,
            { method: "POST" }
          );
          const d = await r.json();
          if (d.ok) deletedCount++;
        } catch {}
        idx++;
        renderItem();
      });

      const skipBtn = document.createElement("button");
      skipBtn.textContent = "건너뛰기";
      Object.assign(skipBtn.style, {
        flex: "1", padding: "5px 0", background: "#45475a",
        color: "#cdd6f4", border: "none", borderRadius: "4px",
        fontWeight: "700", fontSize: "12px", cursor: "pointer",
      });
      skipBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        idx++;
        renderItem();
      });

      btnRow.appendChild(confirmBtn);
      btnRow.appendChild(skipBtn);
      el.appendChild(btnRow);

      el.style.display = "block";
    }

    renderItem();
  }

  function show(exact, partial) {
    const el = getOverlay();
    el.innerHTML = "";

    el.appendChild(makeTopButtons());

    const total = exact.length + partial.length;

    // 헤더 행: 카운트 + 닫기 버튼
    const headerRow = document.createElement("div");
    Object.assign(headerRow.style, { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" });

    const header = document.createElement("div");
    Object.assign(header.style, { color: "#89b4fa", fontWeight: "700", fontSize: "11px" });
    header.textContent = `📁 정확 일치 ${exact.length}개 / 전체 ${total}개`;

    const closeBtn = document.createElement("span");
    closeBtn.textContent = "✕";
    Object.assign(closeBtn.style, { cursor: "pointer", color: "#6c7086", fontSize: "14px", lineHeight: "1", paddingLeft: "8px" });
    closeBtn.addEventListener("mouseenter", () => closeBtn.style.color = "#cdd6f4");
    closeBtn.addEventListener("mouseleave", () => closeBtn.style.color = "#6c7086");
    closeBtn.addEventListener("click", (e) => { e.stopPropagation(); hide(); });

    headerRow.appendChild(header);
    headerRow.appendChild(closeBtn);
    el.appendChild(headerRow);

    // 정확 일치 목록 (초록 배경)
    if (exact.length > 0) {
      exact.forEach((name) => el.appendChild(makeRow(name, true)));
    }

    // 구분선
    if (exact.length > 0 && partial.length > 0) {
      const sep = document.createElement("div");
      Object.assign(sep.style, { borderTop: "1px solid #45475a", margin: "4px 0" });
      el.appendChild(sep);
    }

    // 부분 일치 목록
    if (partial.length > 0) {
      partial.forEach((name) => el.appendChild(makeRow(name, false)));
    }

    // 결과 없음
    if (total === 0) {
      const msg = document.createElement("div");
      Object.assign(msg.style, { color: "#6c7086", fontSize: "12px" });
      msg.textContent = "일치하는 파일 없음";
      el.appendChild(msg);
    }

    const GAP = 12;
    el.style.left = mouseX + "px";
    el.style.top = (mouseY + GAP) + "px";
    el.style.setProperty("display", "block", "important");
    el.style.setProperty("visibility", "visible", "important");
    el.style.setProperty("opacity", "1", "important");
    el.scrollTop = 0;
    clearTimeout(hideTimer);

    requestAnimationFrame(() => {
      const rect = el.getBoundingClientRect();
      let left = parseFloat(el.style.left);
      let top  = parseFloat(el.style.top);
      if (rect.right  > window.innerWidth  - 8) left = window.innerWidth  - rect.width  - 8;
      if (rect.bottom > window.innerHeight - 8) top  = mouseY - rect.height - 4;
      if (left < 4) left = 4;
      if (top  < 4) top  = 4;
      el.style.left = left + "px";
      el.style.top  = top  + "px";
    });
  }

  function hide() {
    if (dedupActive) return;
    clearTimeout(hideTimer);
    if (overlay) overlay.style.setProperty("display", "none", "important");
    lastText = "";
  }

  function extractText(el) {
    let text = "";
    for (const node of el.childNodes) {
      if (node.nodeType === Node.TEXT_NODE) text += node.textContent;
    }
    text = text.trim();
    if (!text) text = (el.innerText || el.textContent || "").trim();
    return text.slice(0, 100);
  }

  async function fetchAndShow(text) {
    if (dedupActive) return;
    try {
      const res = await fetch(`${SERVER}?text=${encodeURIComponent(text)}`);
      if (!res.ok) return;
      const data = await res.json();
      const dataStr = JSON.stringify(data).slice(0, 80);
      fetch(`http://localhost:7823/debug-log?step=got&msg=${encodeURIComponent(dataStr)}`).catch(()=>{});
      if (!data || data.no_search) return;
      show(data.exact || [], data.partial || []);
    } catch {
      // 서버 꺼져있으면 무시
    }
  }

  // 마우스 위치 추적
  document.addEventListener("mousemove", (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
  }, { passive: true });

  // 텍스트 위에 마우스 올릴 때
  document.addEventListener("mouseover", (e) => {
    const target = e.target;
    if (!target || overlay?.contains(target)) return;
    if (overlayHovered) return;

    const text = extractText(target);
    if (!text || text.length < MIN_TEXT_LEN) return;

    // 같은 텍스트면 무시 (오버레이 유지)
    if (text === lastText) return;

    lastText = text;
    clearTimeout(timer);

    timer = setTimeout(() => fetchAndShow(text), DEBOUNCE_MS);
  });

  // 페이지 밖으로 나가면 숨김
  document.addEventListener("mouseleave", () => {
    clearTimeout(timer);
    hide();
  });

  // 팝업 바깥 클릭 시 닫기
  document.addEventListener("click", (e) => {
    if (!overlay?.contains(e.target)) hide();
  });
})();
