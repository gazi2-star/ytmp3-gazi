#!/usr/bin/env python3
"""
ytmp3 - Descargador local de YouTube a MP3 (uso personal).

Uso GUI:   python ytmp3.py
Uso CLI:   python ytmp3.py URL [URL ...] [-o CARPETA] [-q 320] [--playlist]

Requisitos: yt-dlp (pip) y ffmpeg instalado en el PATH.
"""
import argparse
import queue
import shutil
import sys
import threading
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    sys.exit("Falta yt-dlp. Instala con:  pip install -U yt-dlp")

DEFAULT_DIR = Path.home() / "Music" / "YT-MP3"
QUALITIES = ["128", "192", "256", "320"]


def find_ffmpeg():
    """Busca ffmpeg: empaquetado en el .exe, junto al .exe/script, o en el PATH."""
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    candidates = []
    if getattr(sys, "_MEIPASS", None):  # dentro del .exe de PyInstaller
        candidates.append(Path(sys._MEIPASS))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent)
    else:
        candidates.append(Path(__file__).resolve().parent)
    for folder in candidates:
        if (folder / exe).exists():
            return str(folder)
    return str(Path(shutil.which("ffmpeg")).parent) if shutil.which("ffmpeg") else None


def check_ffmpeg():
    loc = find_ffmpeg()
    if loc is None:
        raise RuntimeError(
            "No se encontró ffmpeg. Pon ffmpeg.exe junto al programa "
            "o instálalo (winget install ffmpeg)."
        )
    return loc


def build_opts(out_dir: Path, quality: str, playlist: bool, hook=None, log=None):
    opts = {
        "ffmpeg_location": find_ffmpeg(),
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
        "noplaylist": not playlist,
        "restrictfilenames": False,
        "writethumbnail": True,
        "ignoreerrors": playlist,  # en playlists, saltar vídeos fallidos
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            },
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
            {"key": "FFmpegMetadata", "add_metadata": True},
            {"key": "EmbedThumbnail"},
        ],
    }
    if hook:
        opts["progress_hooks"] = [hook]
    if log:
        opts["logger"] = log
    return opts


def download(urls, out_dir: Path, quality="320", playlist=False, hook=None, log=None):
    check_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL(build_opts(out_dir, quality, playlist, hook, log)) as ydl:
        ydl.download(urls)


# ----------------------------- CLI -----------------------------
def cli_hook(d):
    if d["status"] == "downloading":
        pct = d.get("_percent_str", "").strip()
        speed = d.get("_speed_str", "").strip()
        print(f"\r  {pct} {speed}   ", end="", flush=True)
    elif d["status"] == "finished":
        print("\n  Descarga lista, convirtiendo a MP3...")


def run_cli(args):
    try:
        download(args.urls, Path(args.output).expanduser(), args.quality,
                 args.playlist, hook=cli_hook)
        print(f"\nListo. Archivos en: {Path(args.output).expanduser()}")
    except Exception as e:
        sys.exit(f"Error: {e}")


# ----------------------------- GUI -----------------------------
class _QLogger:
    def __init__(self, q):
        self.q = q

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        self.q.put(("log", f"Aviso: {msg}"))

    def error(self, msg):
        self.q.put(("log", f"Error: {msg}"))


def run_gui():
    import tkinter as tk
    from tkinter import filedialog, ttk

    root = tk.Tk()
    root.title("YT → MP3")
    root.geometry("620x420")
    q: "queue.Queue" = queue.Queue()

    url_var = tk.StringVar()
    dir_var = tk.StringVar(value=str(DEFAULT_DIR))
    q_var = tk.StringVar(value="320")
    pl_var = tk.BooleanVar(value=False)

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)

    ttk.Label(frm, text="URL(s):").grid(row=0, column=0, sticky="w")
    url_entry = ttk.Entry(frm, textvariable=url_var)
    url_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)

    ttk.Label(frm, text="Carpeta:").grid(row=1, column=0, sticky="w")
    ttk.Entry(frm, textvariable=dir_var).grid(row=1, column=1, sticky="ew", pady=4)

    def pick_dir():
        d = filedialog.askdirectory(initialdir=dir_var.get())
        if d:
            dir_var.set(d)

    ttk.Button(frm, text="…", width=3, command=pick_dir).grid(row=1, column=2, padx=(4, 0))

    ttk.Label(frm, text="Calidad (kbps):").grid(row=2, column=0, sticky="w")
    ttk.Combobox(frm, textvariable=q_var, values=QUALITIES, width=6,
                 state="readonly").grid(row=2, column=1, sticky="w", pady=4)
    ttk.Checkbutton(frm, text="Descargar lista completa si es playlist",
                    variable=pl_var).grid(row=3, column=0, columnspan=3, sticky="w")

    bar = ttk.Progressbar(frm, mode="determinate", maximum=100)
    bar.grid(row=5, column=0, columnspan=3, sticky="ew", pady=8)

    log = tk.Text(frm, height=12, state="disabled", wrap="word")
    log.grid(row=6, column=0, columnspan=3, sticky="nsew")
    frm.rowconfigure(6, weight=1)

    def write(msg):
        log.configure(state="normal")
        log.insert("end", msg + "\n")
        log.see("end")
        log.configure(state="disabled")

    btn = ttk.Button(frm, text="Descargar MP3")
    btn.grid(row=4, column=0, columnspan=3, pady=6)

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                q.put(("pct", d["downloaded_bytes"] * 100 / total))
        elif d["status"] == "finished":
            q.put(("pct", 100))
            q.put(("log", "Convirtiendo a MP3..."))

    def worker(urls, out_dir, quality, playlist):
        try:
            download(urls, Path(out_dir).expanduser(), quality, playlist,
                     hook=hook, log=_QLogger(q))
            q.put(("log", f"Listo. Archivos en: {out_dir}"))
        except Exception as e:
            q.put(("log", f"Error: {e}"))
        finally:
            q.put(("done", None))

    def start():
        urls = url_var.get().split()
        if not urls:
            write("Pega al menos una URL.")
            return
        btn.state(["disabled"])
        bar["value"] = 0
        write(f"Descargando {len(urls)} enlace(s)...")
        threading.Thread(
            target=worker,
            args=(urls, dir_var.get(), q_var.get(), pl_var.get()),
            daemon=True,
        ).start()

    btn.configure(command=start)
    url_entry.bind("<Return>", lambda e: start())

    def poll():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "pct":
                    bar["value"] = val
                elif kind == "log":
                    write(val)
                elif kind == "done":
                    btn.state(["!disabled"])
        except queue.Empty:
            pass
        root.after(100, poll)

    poll()
    root.mainloop()


def main():
    p = argparse.ArgumentParser(description="YouTube a MP3 local (uso personal)")
    p.add_argument("urls", nargs="*", help="URL(s) de YouTube; sin ellas se abre la GUI")
    p.add_argument("-o", "--output", default=str(DEFAULT_DIR), help="Carpeta de salida")
    p.add_argument("-q", "--quality", default="320", choices=QUALITIES, help="Bitrate MP3")
    p.add_argument("--playlist", action="store_true", help="Descargar playlist completa")
    args = p.parse_args()

    if args.urls:
        run_cli(args)
    else:
        run_gui()


if __name__ == "__main__":
    main()
