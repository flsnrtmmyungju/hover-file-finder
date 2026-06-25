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
  let hoveredAttachItem = null;
  let _cbarRestoreFn = null;
  let _suppressHashNav = false;
  let _movedDlEls = [];

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
      "이름정리(전체)", "#89dceb",
      "http://localhost:7823/rename",
      (d) => d.error ? "오류" : `✓ ${d.renamed}개 이름변경`
    ));
    wrap.appendChild(makeActionBtn(
      "이름정리(다운)", "#89dceb",
      "http://localhost:7823/rename/downloads",
      (d) => d.error ? "오류" : `✓ ${d.renamed}개 이름변경`
    ));
    wrap.appendChild(makeActionBtn(
      "이름정리(소설)", "#89dceb",
      "http://localhost:7823/rename/archive",
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

    // 뷰어보기 버튼
    const viewerBtn = document.createElement("button");
    viewerBtn.textContent = "뷰어보기";
    Object.assign(viewerBtn.style, {
      flex: "1", padding: "5px 0", background: "#cba6f7",
      color: "#1e1e2e", border: "none", borderRadius: "5px",
      fontWeight: "700", fontSize: "11px", cursor: "pointer",
    });
    viewerBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      viewerBtn.textContent = "열기 중...";
      viewerBtn.disabled = true;
      try {
        const res = await fetch("http://localhost:7823/history");
        const hist = await res.json();
        if (hist.length > 0) {
          openViewerWindow(hist[0].filename);
        } else {
          alert("뷰어 기록이 없습니다.");
        }
      } catch { alert("서버 오류"); }
      setTimeout(() => { viewerBtn.textContent = "뷰어보기"; viewerBtn.disabled = false; }, 2000);
    });
    wrap.appendChild(viewerBtn);

    wrap.appendChild(makeActionBtn(
      "압축풀기", "#a6e3a1",
      "http://localhost:7823/extract-all",
      (d) => d.error ? "오류" : `✓ ${d.extracted}개 압축해제`
    ));
    wrap.appendChild(makeActionBtn(
      "epub변환", "#f9e2af",
      "http://localhost:7823/epub-batch-convert",
      (d) => d.error ? `오류: ${d.error}` : `✓ ${d.converted}개 변환`
    ));

    const archiveBtn = document.createElement("button");
    archiveBtn.textContent = "전체 중복확인";
    Object.assign(archiveBtn.style, {
      flex: "1", padding: "5px 0", background: "#fab387",
      color: "#1e1e2e", border: "none", borderRadius: "5px",
      fontWeight: "700", fontSize: "11px", cursor: "pointer",
    });
    archiveBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      archiveBtn.textContent = "스캔 중...";
      archiveBtn.disabled = true;
      try {
        const res = await fetch("http://localhost:7823/archive-scan", { method: "POST" });
        const data = await res.json();
        if (data.error) { archiveBtn.textContent = "오류"; return; }
        startArchiveScanFlow(data, archiveBtn);
      } catch {
        archiveBtn.textContent = "오류";
      }
      setTimeout(() => { archiveBtn.textContent = "전체 중복확인"; archiveBtn.disabled = false; }, 3000);
    });
    wrap.appendChild(archiveBtn);

    return wrap;
  }

  function startArchiveScanFlow(data, triggerBtn) {
    dedupActive = true;
    triggerBtn.disabled = true;
    const el = getOverlay();
    el.innerHTML = "";

    const escHandler = (e) => { if (e.key === "Escape") { closeFlow(); document.removeEventListener("keydown", escHandler); } };
    document.addEventListener("keydown", escHandler);

    function closeFlow() {
      dedupActive = false;
      triggerBtn.textContent = "전체 중복확인";
      triggerBtn.disabled = false;
      hide();
      document.removeEventListener("keydown", escHandler);
    }

    const hdrRow = document.createElement("div");
    Object.assign(hdrRow.style, { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" });
    const hdr = document.createElement("div");
    Object.assign(hdr.style, { color: "#89b4fa", fontWeight: "700", fontSize: "11px" });
    hdr.textContent = `${data.scanned.toLocaleString()}개 스캔 — 완전동일 ${data.hash_dupes}개 / 같은소설 ${data.title_dupes}그룹`;
    const closeBtn = document.createElement("span");
    closeBtn.textContent = "✕";
    Object.assign(closeBtn.style, { cursor: "pointer", color: "#6c7086", fontSize: "14px" });
    closeBtn.addEventListener("click", (e) => { e.stopPropagation(); closeFlow(); });
    hdrRow.appendChild(hdr); hdrRow.appendChild(closeBtn);
    el.appendChild(hdrRow);

    const tabRow = document.createElement("div");
    Object.assign(tabRow.style, { display: "flex", gap: "4px", marginBottom: "6px" });
    const hashPanel = document.createElement("div");
    const titlePanel = document.createElement("div");
    titlePanel.style.display = "none";

    [["완전동일 (" + data.hash_groups.length + ")", "#f38ba8", hashPanel],
     ["같은소설 (" + data.title_groups.length + ")", "#fab387", titlePanel]].forEach(([label, color, panel], idx) => {
      const tab = document.createElement("button");
      tab.textContent = label;
      Object.assign(tab.style, { flex: "1", padding: "3px 0", border: "none", borderRadius: "4px", fontSize: "10px", fontWeight: "700", cursor: "pointer", background: idx === 0 ? color : "#45475a", color: idx === 0 ? "#1e1e2e" : "#cdd6f4" });
      tab.addEventListener("click", (e) => {
        e.stopPropagation();
        hashPanel.style.display = panel === hashPanel ? "block" : "none";
        titlePanel.style.display = panel === titlePanel ? "block" : "none";
        tabRow.querySelectorAll("button").forEach((b, i) => { b.style.background = i === idx ? color : "#45475a"; b.style.color = i === idx ? "#1e1e2e" : "#cdd6f4"; });
      });
      tabRow.appendChild(tab);
    });
    el.appendChild(tabRow);

    // 완전동일 패널
    if (!data.hash_groups.length) {
      hashPanel.innerHTML = '<div style="color:#6c7086;font-size:11px">완전 동일 파일 없음</div>';
    } else {
      data.hash_groups.forEach((g) => {
        const gdiv = document.createElement("div");
        Object.assign(gdiv.style, { marginBottom: "6px", borderTop: "1px solid #45475a", paddingTop: "4px" });
        const gh = document.createElement("div");
        Object.assign(gh.style, { color: "#f38ba8", fontSize: "10px", fontWeight: "700", marginBottom: "3px" });
        gh.textContent = `${g.files.length}개 동일 · ${g.size_mb}MB`;
        gdiv.appendChild(gh);
        g.files.forEach((f, fi) => {
          const row = document.createElement("div");
          Object.assign(row.style, { display: "flex", alignItems: "center", gap: "6px", padding: "2px 0", fontSize: "11px" });
          const nm = document.createElement("span");
          nm.style.flex = "1"; nm.style.overflow = "hidden"; nm.style.textOverflow = "ellipsis"; nm.style.whiteSpace = "nowrap";
          nm.style.color = fi === 0 ? "#a6e3a1" : "#cdd6f4";
          nm.textContent = (fi === 0 ? "✓ " : "🗑 ") + f.name;
          row.appendChild(nm);
          if (fi > 0) {
            const db = document.createElement("button");
            db.textContent = "삭제";
            Object.assign(db.style, { flexShrink: "0", padding: "1px 6px", background: "#f38ba8", color: "#1e1e2e", border: "none", borderRadius: "3px", fontSize: "10px", fontWeight: "700", cursor: "pointer" });
            db.addEventListener("click", async (e) => {
              e.stopPropagation();
              if (!confirm("삭제?\n" + f.name)) return;
              const r = await fetch("http://localhost:7823/delete-path", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: f.path }) });
              const d = await r.json();
              if (d.ok) { row.style.opacity = "0.3"; nm.textContent = "✓ 삭제: " + f.name; db.remove(); }
              else alert("삭제 실패: " + (d.error || "오류"));
            });
            row.appendChild(db);
          }
          gdiv.appendChild(row);
        });
        hashPanel.appendChild(gdiv);
      });
    }
    el.appendChild(hashPanel);

    // 같은소설 패널
    if (!data.title_groups.length) {
      titlePanel.innerHTML = '<div style="color:#6c7086;font-size:11px">같은 제목 파일 없음</div>';
    } else {
      data.title_groups.forEach((g) => {
        const gdiv = document.createElement("div");
        Object.assign(gdiv.style, { marginBottom: "6px", borderTop: "1px solid #45475a", paddingTop: "4px" });
        const gh = document.createElement("div");
        Object.assign(gh.style, { display: "flex", alignItems: "center", gap: "6px", marginBottom: "3px" });
        const badge = document.createElement("span");
        badge.textContent = g.has_exact_dupe ? "중복" : "같은소설";
        Object.assign(badge.style, { background: g.has_exact_dupe ? "#f38ba8" : "#fab387", color: "#1e1e2e", borderRadius: "3px", padding: "0 5px", fontSize: "10px", fontWeight: "700", flexShrink: "0" });
        const title = document.createElement("span");
        title.style.fontSize = "11px"; title.style.fontWeight = "700"; title.style.overflow = "hidden"; title.style.textOverflow = "ellipsis"; title.style.whiteSpace = "nowrap";
        title.textContent = g.title;
        gh.appendChild(badge); gh.appendChild(title);
        gdiv.appendChild(gh);
        g.files.forEach((f) => {
          const row = document.createElement("div");
          Object.assign(row.style, { display: "flex", alignItems: "center", gap: "6px", padding: "2px 0", fontSize: "11px" });
          const nm = document.createElement("span");
          nm.style.flex = "1"; nm.style.overflow = "hidden"; nm.style.textOverflow = "ellipsis"; nm.style.whiteSpace = "nowrap";
          nm.textContent = f.name;
          const meta = document.createElement("span");
          meta.style.color = "#6c7086"; meta.style.fontSize = "10px"; meta.style.flexShrink = "0"; meta.style.whiteSpace = "nowrap";
          meta.textContent = (f.ep ? f.ep + " " : "") + f.size_mb + "MB";
          const db = document.createElement("button");
          db.textContent = "삭제";
          Object.assign(db.style, { flexShrink: "0", padding: "1px 6px", background: "#f38ba8", color: "#1e1e2e", border: "none", borderRadius: "3px", fontSize: "10px", fontWeight: "700", cursor: "pointer" });
          db.addEventListener("click", async (e) => {
            e.stopPropagation();
            if (!confirm("삭제?\n" + f.name)) return;
            const r = await fetch("http://localhost:7823/delete-path", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: f.path }) });
            const d = await r.json();
            if (d.ok) { row.style.opacity = "0.3"; nm.textContent = "✓ 삭제: " + f.name; db.remove(); }
            else alert("삭제 실패: " + (d.error || "오류"));
          });
          row.appendChild(nm); row.appendChild(meta); row.appendChild(db);
          gdiv.appendChild(row);
        });
        titlePanel.appendChild(gdiv);
      });
    }
    el.appendChild(titlePanel);
    el.style.setProperty("display", "block", "important");
    el.scrollTop = 0;
  }

  function startDedupFlow(items, triggerBtn) {
    dedupActive = true;
    triggerBtn.disabled = true;
    const el = getOverlay();
    const checks = new Map(); // item index → checkbox element

    function closeDedup() {
      dedupActive = false;
      triggerBtn.textContent = "중복삭제";
      triggerBtn.disabled = false;
      hide();
    }

    const escHandler = (e) => {
      if (e.key === "Escape") { closeDedup(); document.removeEventListener("keydown", escHandler); }
    };
    document.addEventListener("keydown", escHandler);

    // ── 체크리스트 렌더 ──────────────────────────────────────────
    el.innerHTML = "";

    // 헤더
    const headerRow = document.createElement("div");
    Object.assign(headerRow.style, { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" });
    const hdr = document.createElement("div");
    Object.assign(hdr.style, { color: "#89b4fa", fontWeight: "700", fontSize: "11px" });
    hdr.textContent = `중복 ${items.length}개 — 삭제할 항목 선택`;
    const closeBtn = document.createElement("span");
    closeBtn.textContent = "✕";
    Object.assign(closeBtn.style, { cursor: "pointer", color: "#6c7086", fontSize: "14px" });
    closeBtn.addEventListener("click", (e) => { e.stopPropagation(); document.removeEventListener("keydown", escHandler); closeDedup(); });
    headerRow.appendChild(hdr);
    headerRow.appendChild(closeBtn);
    el.appendChild(headerRow);

    // 전체선택/해제 버튼
    const selRow = document.createElement("div");
    Object.assign(selRow.style, { display: "flex", gap: "6px", marginBottom: "6px" });
    ["전체선택", "전체해제"].forEach((label, i) => {
      const b = document.createElement("button");
      b.textContent = label;
      Object.assign(b.style, { padding: "2px 8px", background: "#45475a", color: "#cdd6f4", border: "none", borderRadius: "3px", fontSize: "10px", cursor: "pointer" });
      b.addEventListener("click", (e) => { e.stopPropagation(); checks.forEach(cb => cb.checked = i === 0); });
      selRow.appendChild(b);
    });
    el.appendChild(selRow);

    // 항목 목록
    const listDiv = document.createElement("div");
    Object.assign(listDiv.style, { maxHeight: "220px", overflowY: "auto", marginBottom: "8px" });

    items.forEach((item, i) => {
      const row = document.createElement("div");
      Object.assign(row.style, { display: "flex", alignItems: "flex-start", gap: "6px", padding: "5px 0", borderTop: "1px solid #313244" });

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = true;
      Object.assign(cb.style, { marginTop: "2px", flexShrink: "0", cursor: "pointer" });
      checks.set(i, cb);

      const info = document.createElement("div");
      Object.assign(info.style, { fontSize: "11px", lineHeight: "1.5" });
      const delSize = item.delete_size != null ? ` <span style="color:#6c7086">${item.delete_size}MB</span>` : "";
      const keepSize = item.keep_size != null ? ` <span style="color:#6c7086">${item.keep_size}MB</span>` : "";
      info.innerHTML =
        `<div><span style="color:#f38ba8">🗑</span> [${item.delete_loc}] ${item.delete_name}${delSize}</div>` +
        `<div><span style="color:#a6e3a1">✓</span> [${item.keep_loc}] ${item.keep_name}${keepSize}</div>` +
        `<div style="color:#6c7086;font-size:10px">${item.reason}</div>`;

      row.appendChild(cb);
      row.appendChild(info);
      listDiv.appendChild(row);
    });
    el.appendChild(listDiv);

    // 삭제 실행 버튼
    const execBtn = document.createElement("button");
    execBtn.textContent = "선택 삭제";
    Object.assign(execBtn.style, {
      width: "100%", padding: "6px 0", background: "#f38ba8",
      color: "#1e1e2e", border: "none", borderRadius: "4px",
      fontWeight: "700", fontSize: "12px", cursor: "pointer",
    });
    execBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      execBtn.disabled = true;
      execBtn.textContent = "삭제 중...";
      let deleted = 0;
      for (const [i, cb] of checks) {
        if (!cb.checked) continue;
        try {
          const r = await fetch(
            `http://localhost:7823/delete-path?path=${encodeURIComponent(items[i].delete_path)}`,
            { method: "POST" }
          );
          const d = await r.json();
          if (d.ok) deleted++;
        } catch {}
      }
      el.innerHTML = "";
      const done = document.createElement("div");
      Object.assign(done.style, { color: "#a6e3a1", fontWeight: "700", padding: "8px 0" });
      done.textContent = `✓ ${deleted}개 삭제 완료`;
      el.appendChild(done);
      triggerBtn.textContent = `✓ ${deleted}개 삭제`;
      dedupActive = false;
      document.removeEventListener("keydown", escHandler);
      setTimeout(() => { triggerBtn.textContent = "중복삭제"; triggerBtn.disabled = false; }, 3000);
    });
    el.appendChild(execBtn);

    el.style.setProperty("display", "block", "important");
    el.scrollTop = 0;
  }

  // ── toki.org 첨부파일 헬퍼 ───────────────────────────────────────
  function closestAttachItem(target) {
    return target.closest(".post-attach-item") || target.closest(".theme-board-attach-item") || null;
  }

  function getItemInfo(item) {
    const themeNameEl = item.querySelector(".theme-board-attach-name");
    if (themeNameEl) {
      const rawName = (themeNameEl.getAttribute("title") || themeNameEl.textContent).normalize('NFC').replace(/^[^\w가-힣\[（(]+/, '').trim();
      const dlEl = item.querySelector("button[data-theme-attach-download]") || null;
      return { rawName, dlEl };
    }
    const nameEl = item.querySelector(".post-attach-name");
    const rawName = nameEl ? nameEl.textContent.normalize('NFC').replace(/^[^\w가-힣\[（(]+/, '').trim() : '';
    const dlEl = item.querySelector('button[title*="다운로드"]:not([title*="선택"]):not([disabled])') ||
                 item.querySelector('.post-attach-actions button:last-child') || null;
    return { rawName, dlEl };
  }

  function getPageAttachItems() {
    const themeList = document.querySelector(".theme-board-attach-list");
    if (themeList) {
      return [...themeList.querySelectorAll(".theme-board-attach-item")].map(li => {
        const nameEl = li.querySelector(".theme-board-attach-name");
        const rawName = (nameEl?.getAttribute("title") || nameEl?.textContent || '').normalize('NFC').replace(/^[^\w가-힣\[（(]+/, '').trim();
        const size = li.querySelector(".theme-board-attach-sub")?.textContent.trim() || null;
        const dlEl = li.querySelector("button[data-theme-attach-download]") || null;
        return { rawName, size, dlEl };
      });
    }
    const postList = document.querySelector(".post-attach-list");
    if (postList) {
      return [...postList.querySelectorAll(".post-attach-item")].map(li => {
        const nameEl = li.querySelector(".post-attach-name");
        const rawName = nameEl ? nameEl.textContent.normalize('NFC').replace(/^[^\w가-힣\[（(]+/, '').trim() : '';
        const size = li.querySelector(".post-attach-size")?.textContent.trim() || null;
        const dlEl = li.querySelector('button[title*="다운로드"]:not([title*="선택"]):not([disabled])') ||
                     li.querySelector('.post-attach-actions button:last-child') || null;
        return { rawName, size, dlEl };
      });
    }
    return [];
  }

  function findDownloadEl(rawName) {
    const needle = rawName.normalize('NFC').replace(/^[^\w가-힣\[]+/, '').slice(0, 12);
    if (!needle) return null;
    for (const item of [...document.querySelectorAll('.post-attach-item,.theme-board-attach-item')]) {
      const nameEl = item.querySelector('.post-attach-name') || item.querySelector('.theme-board-attach-name');
      if ((nameEl?.textContent || '').normalize('NFC').includes(needle)) {
        return item.querySelector('button[title*="다운로드"]:not([title*="선택"])') ||
               item.querySelector('button[data-theme-attach-download]') ||
               item.querySelector('.post-attach-actions button:last-child') || null;
      }
    }
    return null;
  }

  function clearMulti() {
    _movedDlEls.forEach(({ el: vel, parent, next }) => {
      try {
        if (parent && document.body.contains(parent))
          next && parent.contains(next) ? parent.insertBefore(vel, next) : parent.appendChild(vel);
      } catch {}
    });
    _movedDlEls = [];
    if (_cbarRestoreFn) { _cbarRestoreFn(); _cbarRestoreFn = null; }
    _suppressHashNav = false;
  }

  function openViewerWindow(filename) {
    window.postMessage({ type: 'open-viewer', filename }, '*');
  }

  // ── 페이지 전체 소설 목록 표시 (toki.org) ───────────────────────
  function showMultiple(items) {
    clearMulti();
    const el = getOverlay();
    el.innerHTML = "";
    Object.assign(el.style, { width: "380px", maxHeight: "380px" });

    el.appendChild(makeTopButtons());

    const hdrRow = document.createElement("div");
    Object.assign(hdrRow.style, { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" });
    const hdr = document.createElement("div");
    Object.assign(hdr.style, { color: "#89b4fa", fontWeight: "700", fontSize: "11px" });
    hdr.textContent = `📋 페이지 소설 ${items.length}개`;
    const closeBtn = document.createElement("span");
    closeBtn.textContent = "✕";
    Object.assign(closeBtn.style, { cursor: "pointer", color: "#6c7086", fontSize: "14px" });
    closeBtn.addEventListener("click", (e) => { e.stopPropagation(); hide(); });
    hdrRow.appendChild(hdr); hdrRow.appendChild(closeBtn);
    el.appendChild(hdrRow);

    const listDiv = document.createElement("div");
    Object.assign(listDiv.style, { maxHeight: "280px", overflowY: "auto" });

    const _dlBtnStyle = {
      fontSize: "10px", padding: "0 10px", flexShrink: "0",
      height: "22px", lineHeight: "22px",
      background: "linear-gradient(135deg, #89b4fa, #74c7ec)",
      color: "#1e1e2e", border: "none", borderRadius: "4px",
      fontWeight: "700", cursor: "pointer", boxSizing: "border-box",
    };

    items.forEach(({ text: searchText, displayName, size, dlEl, siteIndex }) => {
      const section = document.createElement("div");
      Object.assign(section.style, { borderTop: "1px solid #313244", paddingTop: "5px", marginBottom: "3px" });

      const topRow = document.createElement("div");
      Object.assign(topRow.style, { display: "flex", alignItems: "center", gap: "5px", marginBottom: "2px" });

      const idx = document.createElement("span");
      idx.textContent = `#${siteIndex}`;
      Object.assign(idx.style, { flexShrink: "0", color: "#6c7086", fontSize: "10px", fontWeight: "700" });

      const nm = document.createElement("span");
      Object.assign(nm.style, { flex: "1", fontSize: "11px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#cdd6f4" });
      nm.textContent = displayName || searchText;

      topRow.appendChild(idx);
      topRow.appendChild(nm);

      if (size) {
        const sz = document.createElement("span");
        Object.assign(sz.style, { flexShrink: "0", fontSize: "10px", color: "#6c7086" });
        sz.textContent = size;
        topRow.appendChild(sz);
      }

      // 다운로드 버튼
      const rawName = displayName || searchText;
      const dl = dlEl || findDownloadEl(rawName);
      if (dl) {
        if (dl.hasAttribute('data-theme-attach-download')) {
          const proxy = document.createElement("button");
          proxy.textContent = "다운로드";
          Object.assign(proxy.style, _dlBtnStyle);
          proxy.addEventListener("click", async (e) => {
            e.stopPropagation();
            const wrap = dl.closest('[data-theme-attachments]');
            const isPaid = wrap?.getAttribute('data-is-paid') === '1' && wrap?.getAttribute('data-free') !== '1';
            if (isPaid || !wrap) { dl.click(); return; }
            const postId = wrap.getAttribute('data-post-id') || '';
            const idx2 = dl.getAttribute('data-attach-index') || '0';
            const fname = dl.getAttribute('data-file-name') || 'download';
            const url = `/api/board/file?p=${encodeURIComponent(postId)}&i=${encodeURIComponent(idx2)}`;
            proxy.disabled = true; proxy.textContent = '확인중';
            try {
              const chk = await fetch(url + '&check=1', { credentials: 'same-origin', headers: { Accept: 'application/json' } });
              if (!chk.ok) { const j = await chk.json().catch(() => null); throw new Error(j?.error || '다운로드 불가'); }
              const a = document.createElement('a'); a.href = url; a.download = fname; a.rel = 'noreferrer';
              document.body.appendChild(a); a.click(); a.remove();
              proxy.textContent = '완료'; setTimeout(() => { proxy.textContent = '다운로드'; proxy.disabled = false; }, 2000);
            } catch (err) {
              proxy.textContent = (err.message || '실패').slice(0, 8);
              setTimeout(() => { proxy.textContent = '다운로드'; proxy.disabled = false; }, 3000);
            }
          });
          topRow.appendChild(proxy);
        } else {
          const dlParent = dl.parentElement;
          const dlNext = dl.nextSibling;
          _movedDlEls.push({ el: dl, parent: dlParent, next: dlNext });
          Object.assign(dl.style, _dlBtnStyle);
          topRow.appendChild(dl);
        }
      }

      section.appendChild(topRow);

      // 서버 검색 결과
      const resultDiv = document.createElement("div");
      Object.assign(resultDiv.style, { fontSize: "10px", color: "#6c7086", paddingLeft: "16px", marginBottom: "2px" });
      resultDiv.textContent = "검색 중...";
      section.appendChild(resultDiv);

      fetch(`${SERVER}?text=${encodeURIComponent(searchText)}`)
        .then(r => r.json())
        .then(data => {
          resultDiv.innerHTML = "";
          resultDiv.style.paddingLeft = "0";
          if (data.no_search) { resultDiv.textContent = "검색 불가"; return; }
          const exact = data.exact || [], partial = data.partial || [];
          if (!exact.length && !partial.length) {
            const none = document.createElement("div");
            Object.assign(none.style, { color: "#6c7086", fontSize: "10px", padding: "2px 0 2px 16px" });
            none.textContent = "미보유";
            resultDiv.appendChild(none);
            return;
          }
          const makeName = (item, isExact) => {
            const name = typeof item === "object" ? item.name : item;
            const size = typeof item === "object" ? item.size : null;
            const row = document.createElement("div");
            Object.assign(row.style, {
              display: "flex", alignItems: "center", gap: "5px",
              padding: "2px 4px 2px 16px", fontSize: "10px",
              background: isExact ? "rgba(166,227,161,0.15)" : "rgba(249,226,175,0.08)",
              borderLeft: `2px solid ${isExact ? "#a6e3a1" : "#f9e2af"}`,
              marginBottom: "1px", borderRadius: "0 3px 3px 0",
            });
            const lbl = document.createElement("span");
            Object.assign(lbl.style, { flex: "1", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: isExact ? "#a6e3a1" : "#f9e2af" });
            lbl.textContent = name;
            row.appendChild(lbl);
            if (size) {
              const sz = document.createElement("span");
              Object.assign(sz.style, { flexShrink: "0", color: "#6c7086" });
              sz.textContent = size + "MB";
              row.appendChild(sz);
            }
            return row;
          };
          if (exact.length) {
            const hd = document.createElement("div");
            Object.assign(hd.style, { fontSize: "10px", color: "#a6e3a1", fontWeight: "700", padding: "2px 0 1px 16px" });
            hd.textContent = `✓ 정확 ${exact.length}개`;
            resultDiv.appendChild(hd);
            exact.forEach(it => resultDiv.appendChild(makeName(it, true)));
          }
          if (partial.length) {
            const hd = document.createElement("div");
            Object.assign(hd.style, { fontSize: "10px", color: "#f9e2af", fontWeight: "700", padding: "3px 0 1px 16px" });
            hd.textContent = `~ 유사 ${partial.length}개`;
            resultDiv.appendChild(hd);
            partial.forEach(it => resultDiv.appendChild(makeName(it, false)));
          }
        })
        .catch(() => { resultDiv.textContent = "서버 오류"; resultDiv.style.color = "#f38ba8"; });

      listDiv.appendChild(section);
    });

    el.appendChild(listDiv);

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
      let left = parseFloat(el.style.left), top = parseFloat(el.style.top);
      if (rect.right  > window.innerWidth  - 8) left = window.innerWidth  - rect.width  - 8;
      if (rect.bottom > window.innerHeight - 8) top  = mouseY - rect.height - 4;
      if (left < 4) left = 4;
      if (top  < 4) top  = 4;
      el.style.left = left + "px";
      el.style.top  = top  + "px";
    });
  }

  // ── 댓글 + 추천 바 ──────────────────────────────────────────────
  function buildCommentBar() {
    const textarea  = document.querySelector('form.comment-form textarea') ||
                      document.querySelector('.theme-board-comment-form textarea') ||
                      document.querySelector('textarea[placeholder*="댓글"]');
    const submitBtn = document.querySelector('form.comment-form button[type="submit"]') ||
                      document.querySelector('.comment-form-foot button[type="submit"]') ||
                      document.querySelector('.theme-board-comment-form-foot button[type="submit"]');
    const voteBtn   = document.querySelector('.post-vote.post-vote--up') ||
                      document.querySelector('.post-vote-wrap button') ||
                      document.querySelector('a.view-good[data-board-post-vote]');

    if (!textarea && !voteBtn) return;

    const el = getOverlay();

    const saved = voteBtn ? [{ el: voteBtn, parent: voteBtn.parentElement, next: voteBtn.nextSibling, style: voteBtn.getAttribute("style") || "" }] : [];
    if (voteBtn && voteBtn.tagName === 'A' && voteBtn.getAttribute('href') === '#') _suppressHashNav = true;
    _cbarRestoreFn = () => {
      _suppressHashNav = false;
      saved.forEach(({ el: vel, parent, next, style }) => {
        try { vel.setAttribute("style", style); if (parent && document.body.contains(parent)) next && parent.contains(next) ? parent.insertBefore(vel, next) : parent.appendChild(vel); } catch {}
      });
    };

    const sep = document.createElement("div");
    Object.assign(sep.style, { borderTop: "1px solid #45475a", margin: "8px 0 6px" });
    el.appendChild(sep);

    if (voteBtn) {
      // 현재 추천 수 읽기
      const countEl = voteBtn.querySelector('.count,.num,.vote-count,em,strong') ||
                      voteBtn.parentElement?.querySelector('.count,.num,.vote-count,em') ||
                      (voteBtn.tagName === 'A' ? voteBtn : null);
      const rawCount = countEl ? countEl.textContent.replace(/[^0-9]/g, '') : '';
      const curCount = rawCount ? parseInt(rawCount, 10) : null;

      const vb = document.createElement("button");
      const countLabel = curCount !== null ? ` (${curCount} → ${curCount + 1})` : '';
      vb.textContent = `👍 추천${countLabel}`;
      Object.assign(vb.style, { padding: "4px 12px", background: "#a6e3a1", color: "#1e1e2e", border: "none", borderRadius: "4px", fontSize: "11px", fontWeight: "700", cursor: "pointer", marginBottom: "6px" });
      vb.addEventListener("click", (e) => {
        e.stopPropagation();
        voteBtn.click();
        const next = curCount !== null ? curCount + 1 : null;
        vb.textContent = next !== null ? `✓ 추천됨 (${next})` : "✓ 추천됨";
        vb.disabled = true;
      });
      el.appendChild(vb);
    }

    if (textarea && submitBtn) {
      const ta = document.createElement("textarea");
      Object.assign(ta.style, { width: "100%", height: "56px", background: "#313244", color: "#cdd6f4", border: "1px solid #45475a", borderRadius: "4px", fontSize: "11px", padding: "5px 8px", boxSizing: "border-box", resize: "none", outline: "none", display: "block" });
      ta.placeholder = "댓글 입력...";
      ta.addEventListener("click", (e) => e.stopPropagation());
      ta.addEventListener("keydown", (e) => e.stopPropagation());

      const sb = document.createElement("button");
      sb.textContent = "댓글 등록";
      Object.assign(sb.style, { width: "100%", marginTop: "4px", padding: "5px 0", background: "#89b4fa", color: "#1e1e2e", border: "none", borderRadius: "4px", fontSize: "11px", fontWeight: "700", cursor: "pointer" });
      sb.addEventListener("click", (e) => {
        e.stopPropagation();
        const txt = ta.value.trim();
        if (!txt) return;
        textarea.value = txt;
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
        submitBtn.click();
        sb.textContent = "✓ 등록"; sb.disabled = true;
      });

      el.appendChild(ta);
      el.appendChild(sb);
    }
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
    clearMulti();
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

  function showLoading() {
    const el = getOverlay();
    el.innerHTML = "";
    const msg = document.createElement("div");
    Object.assign(msg.style, { color: "#6c7086", fontSize: "12px", padding: "4px 0" });
    msg.textContent = "검색 중...";
    el.appendChild(msg);
    el.style.left = mouseX + "px";
    el.style.top = (mouseY + 12) + "px";
    el.style.setProperty("display", "block", "important");
  }

  async function fetchAndShow(text) {
    if (dedupActive) return;
    showLoading();
    try {
      const res = await fetch(`${SERVER}?text=${encodeURIComponent(text)}`);
      if (!res.ok) { hide(); return; }
      const data = await res.json();
      if (!data || data.no_search) {
        hide();
        lastText = "";
        return;
      }
      show(data.exact || [], data.partial || []);
    } catch {
      hide();
      lastText = "";
    }
  }

  // 마우스 위치 추적 + 호버 아이템 추적
  document.addEventListener("mousemove", (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
    hoveredAttachItem = closestAttachItem(e.target);
  }, { passive: true });

  // 우클릭 시 검색
  document.addEventListener("contextmenu", (e) => {
    if (dedupActive) return;
    if (overlay?.contains(e.target)) return;

    // attach-item 위에서 우클릭 → 단일 파일 검색
    const item = hoveredAttachItem;
    if (item) {
      const { rawName, dlEl } = getItemInfo(item);
      const searchText = rawName.replace(/\.[^.]+$/, '').trim();
      if (searchText.length >= MIN_TEXT_LEN) {
        clearMulti();
        e.preventDefault();
        lastText = searchText;
        clearTimeout(timer);
        fetchAndShow(searchText);
        return;
      }
    }

    // 페이지에 첨부파일 목록이 있으면 전체 자동 읽기
    const pageAttachItems = getPageAttachItems();
    if (pageAttachItems.length > 0) {
      const items = pageAttachItems.map(({ rawName, size, dlEl }, i) => {
        const searchText = rawName.replace(/\.[^.]+$/, '').trim();
        return searchText.length >= MIN_TEXT_LEN ? { text: searchText, displayName: rawName, size, dlEl, siteIndex: i + 1 } : null;
      }).filter(Boolean);
      if (items.length > 0) {
        e.preventDefault();
        lastText = "__multi__";
        showMultiple(items);
        buildCommentBar();
        return;
      }
    }

    const text = extractText(e.target);
    if (!text || text.length < MIN_TEXT_LEN) {
      hide();
      return;
    }

    e.preventDefault();

    // 같은 텍스트 재우클릭 → 닫기
    if (text === lastText) {
      hide();
      return;
    }

    lastText = text;
    clearTimeout(timer);
    fetchAndShow(text);
  });

  // 중간 클릭 → attach-item 단일 검색
  document.addEventListener("auxclick", (e) => {
    if (e.button !== 1) return;
    if (overlay?.contains(e.target)) return;
    const item = closestAttachItem(e.target);
    if (!item) return;
    const { rawName } = getItemInfo(item);
    const searchText = rawName.replace(/\.[^.]+$/, '').trim();
    if (searchText.length < MIN_TEXT_LEN) return;
    clearMulti();
    e.preventDefault();
    lastText = searchText;
    fetchAndShow(searchText);
  });

  // a.view-good href="#" 스크롤 방지
  document.addEventListener("click", (e) => {
    if (_suppressHashNav && e.target.matches('a[href="#"]')) {
      e.preventDefault();
    }
    if (!overlay?.contains(e.target)) hide();
  });
})();
