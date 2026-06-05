import sys
import os
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
from pathlib import Path

# PyInstaller 번들 경로 추가
if getattr(sys, 'frozen', False):
    sys.path.insert(0, sys._MEIPASS)

# EXE 실행 시 실행파일 옆 경로, 스크립트 실행 시 파일 옆 경로
BASE_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"

try:
    import server as _srv
except Exception as _e:
    import tkinter as _tk
    _tk.Tk().withdraw()
    messagebox.showerror("시작 오류", f"서버 모듈 로드 실패:\n{_e}")
    sys.exit(1)

DEFAULT_CONFIG = {
    "downloads_dir": "",
    "archive_folder": "archive",
    "allowed_origins": [],
    "port": 7823,
    "max_results": 10,
    "min_word_length": 2
}

BG       = "#1e1e2e"
BG2      = "#313244"
BG3      = "#45475a"
FG       = "#cdd6f4"
FG_DIM   = "#6c7086"
ACCENT   = "#89b4fa"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
FONT     = ("Segoe UI", 10)
FONT_B   = ("Segoe UI", 10, "bold")
MONO     = ("Consolas", 9)


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class App:
    def __init__(self):
        self.win = tk.Tk()
        self.win.title("Hover File Finder")
        self.win.geometry("660x540")
        self.win.configure(bg=BG)
        self.win.resizable(True, True)
        self._flask_thread = None
        self._build()
        self._load_to_ui()
        self._start_server()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI 빌드 ────────────────────────────────────────────────────
    def _build(self):
        # 상단 상태 바
        top = tk.Frame(self.win, bg=BG2, pady=8)
        top.pack(fill=tk.X)
        self._dot = tk.Label(top, text="●", font=("Segoe UI", 14), bg=BG2, fg=FG_DIM)
        self._dot.pack(side=tk.LEFT, padx=(14, 6))
        self._status = tk.Label(top, text="시작 중...", font=FONT, bg=BG2, fg=FG)
        self._status.pack(side=tk.LEFT)

        pad = dict(padx=14, pady=6)

        # 설정 섹션
        section = tk.LabelFrame(self.win, text=" 설정 ", font=FONT_B,
                                 bg=BG, fg=ACCENT, bd=0, padx=12, pady=8)
        section.pack(fill=tk.X, **pad)
        section.columnconfigure(1, weight=1)

        # 다운로드 폴더
        tk.Label(section, text="다운로드 폴더", font=FONT, bg=BG, fg=FG).grid(
            row=0, column=0, sticky=tk.W, pady=5)
        row0 = tk.Frame(section, bg=BG)
        row0.grid(row=0, column=1, sticky=tk.EW, padx=(10, 0), pady=5)
        self._dl_var = tk.StringVar()
        tk.Entry(row0, textvariable=self._dl_var, font=FONT,
                 bg=BG2, fg=FG, relief=tk.FLAT, insertbackground=FG, bd=4
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(row0, text="📁 선택", command=self._browse_dl,
                  bg=BG3, fg=FG, relief=tk.FLAT, padx=8, font=FONT,
                  activebackground=ACCENT, cursor="hand2"
                  ).pack(side=tk.LEFT, padx=(6, 0))

        # Archive 폴더명
        tk.Label(section, text="Archive 폴더명", font=FONT, bg=BG, fg=FG).grid(
            row=1, column=0, sticky=tk.W, pady=5)
        row1 = tk.Frame(section, bg=BG)
        row1.grid(row=1, column=1, sticky=tk.EW, padx=(10, 0), pady=5)
        self._arc_var = tk.StringVar()
        tk.Entry(row1, textvariable=self._arc_var, font=FONT,
                 bg=BG2, fg=FG, relief=tk.FLAT, insertbackground=FG, bd=4, width=22
                 ).pack(side=tk.LEFT)
        tk.Label(row1, text="  다운로드 폴더 안에 생성되는 정리 폴더",
                 font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack(side=tk.LEFT)

        # 허용 사이트
        tk.Label(section, text="허용 사이트 URL", font=FONT, bg=BG, fg=FG).grid(
            row=2, column=0, sticky=tk.NW, pady=5)
        origins_frame = tk.Frame(section, bg=BG)
        origins_frame.grid(row=2, column=1, sticky=tk.EW, padx=(10, 0), pady=5)
        tk.Label(origins_frame, text="한 줄에 하나씩   예) https://example*.com",
                 font=("Segoe UI", 8), bg=BG, fg=FG_DIM).pack(anchor=tk.W)
        self._origins_txt = tk.Text(origins_frame, height=3, font=FONT,
                                     bg=BG2, fg=FG, relief=tk.FLAT, insertbackground=FG, bd=4)
        self._origins_txt.pack(fill=tk.X)

        # 포트
        tk.Label(section, text="포트", font=FONT, bg=BG, fg=FG).grid(
            row=3, column=0, sticky=tk.W, pady=5)
        row3 = tk.Frame(section, bg=BG)
        row3.grid(row=3, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        self._port_var = tk.StringVar(value="7823")
        tk.Entry(row3, textvariable=self._port_var, font=FONT,
                 bg=BG2, fg=FG, relief=tk.FLAT, insertbackground=FG, bd=4, width=8
                 ).pack(side=tk.LEFT)
        tk.Label(row3, text="  변경 시 프로그램 재시작 필요",
                 font=("Segoe UI", 8), bg=BG, fg=FG_DIM).pack(side=tk.LEFT)

        # 저장 버튼
        btn_row = tk.Frame(self.win, bg=BG)
        btn_row.pack(fill=tk.X, padx=14, pady=(0, 6))
        tk.Button(btn_row, text="  저장  ", command=self._save,
                  bg=ACCENT, fg=BG, relief=tk.FLAT, padx=12, pady=6,
                  font=FONT_B, cursor="hand2", activebackground="#74c7ec"
                  ).pack(side=tk.RIGHT)

        # 로그
        log_frame = tk.LabelFrame(self.win, text=" 서버 로그 ", font=FONT_B,
                                   bg=BG, fg=ACCENT, bd=0)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
        self._log = scrolledtext.ScrolledText(
            log_frame, font=MONO, bg="#11111b", fg="#a6e3a1",
            relief=tk.FLAT, state=tk.DISABLED, bd=6)
        self._log.pack(fill=tk.BOTH, expand=True)

    # ── 폴더 선택 ─────────────────────────────────────────────────
    def _browse_dl(self):
        folder = filedialog.askdirectory(title="다운로드 폴더 선택")
        if folder:
            self._dl_var.set(os.path.normpath(folder))

    # ── 설정 로드/저장 ────────────────────────────────────────────
    def _load_to_ui(self):
        cfg = load_config()
        self._dl_var.set(cfg.get("downloads_dir", ""))
        self._arc_var.set(cfg.get("archive_folder", "archive"))
        self._port_var.set(str(cfg.get("port", 7823)))
        origins = cfg.get("allowed_origins", [])
        self._origins_txt.delete("1.0", tk.END)
        self._origins_txt.insert("1.0", "\n".join(origins))

    def _get_config(self):
        raw = self._origins_txt.get("1.0", tk.END).strip()
        origins = [o.strip() for o in raw.splitlines() if o.strip()]
        try:
            port = int(self._port_var.get())
        except ValueError:
            port = 7823
        return {
            "downloads_dir":  self._dl_var.get(),
            "archive_folder": self._arc_var.get() or "archive",
            "allowed_origins": origins,
            "port":           port,
            "max_results":    10,
            "min_word_length": 2,
        }

    def _save(self):
        save_config(self._get_config())
        self._log_write("✓ 설정 저장됨")
        messagebox.showinfo("저장 완료", "설정이 저장되었습니다.\n포트 변경 시 프로그램을 재시작하세요.")

    # ── 서버 시작 ─────────────────────────────────────────────────
    def _start_server(self):
        import server as srv
        cfg = load_config()
        port = cfg.get("port", 7823)

        def run():
            self._log_write(f"서버 시작: http://localhost:{port}")
            dl = resolve_downloads_dir_local(cfg.get("downloads_dir", ""))
            self._log_write(f"다운로드 폴더: {dl}")
            try:
                import logging
                log = logging.getLogger("werkzeug")
                log.setLevel(logging.ERROR)
                srv.app.run(port=port, debug=False, use_reloader=False)
            except Exception as e:
                self._log_write(f"오류: {e}")
                self._set_status(False)

        self._set_status(True, port)
        self._flask_thread = threading.Thread(target=run, daemon=True)
        self._flask_thread.start()

    def _set_status(self, running, port=None):
        if running and port:
            self._dot.config(fg=GREEN)
            self._status.config(text=f"실행 중  http://localhost:{port}")
        else:
            self._dot.config(fg=RED)
            self._status.config(text="오류 - 포트 충돌 또는 서버 실패")

    def _log_write(self, msg):
        self._log.config(state=tk.NORMAL)
        self._log.insert(tk.END, msg + "\n")
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

    def _on_close(self):
        if messagebox.askokcancel("종료", "서버를 종료하고 프로그램을 닫을까요?"):
            self.win.destroy()

    def run(self):
        self.win.mainloop()


def resolve_downloads_dir_local(raw_path):
    """GUI에서 표시용 경로 변환"""
    return raw_path  # Windows EXE에서는 그대로


if __name__ == "__main__":
    App().run()
