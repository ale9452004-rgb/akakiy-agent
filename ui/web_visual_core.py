"""
Web Visual Core Bridge for Akakiy 2.0.

Provides an isolated, high-performance WebGL2 visual engine powered by Microsoft Edge / WebView2,
serving assets/akakiy_core and maintaining bidirectional real-time state synchronization
between Python and the GPU shader without blocking the Tkinter event loop.
"""

import sys
import os
import json
import time
import socket
import asyncio
import threading
import subprocess
import shutil
import tempfile
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Set

try:
    import websockets
except ImportError:
    websockets = None


def find_edge_binary() -> Optional[str]:
    """Находит исполняемый файл Microsoft Edge или WebView2 на Windows."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application\msedgewebview2.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    # Поиск версионных папок WebView2
    wv_base = r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application"
    if os.path.exists(wv_base):
        for entry in os.listdir(wv_base):
            p = os.path.join(wv_base, entry, "msedgewebview2.exe")
            if os.path.exists(p):
                return p

    return None


def get_free_port() -> int:
    """Возвращает свободный TCP порт."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AkakiyStaticHTTPHandler(SimpleHTTPRequestHandler):
    """Раздаёт статические файлы из assets/akakiy_core без кэширования."""

    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=str(directory), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format, *args):
        # Подавление шума в логах
        pass


class AkakiyVisualBridge:
    """
    Мост управления между Python Agent Core / GUI и аппаратным WebGL визуализатором.
    """

    VALID_STATES = ("idle", "listening", "thinking", "working", "speaking", "success", "error")

    def __init__(self, assets_dir: Optional[Path] = None, http_port: Optional[int] = None, ws_port: Optional[int] = None):
        if assets_dir is None:
            self.assets_dir = Path(__file__).resolve().parent.parent / "assets" / "akakiy_core"
        else:
            self.assets_dir = Path(assets_dir)

        self.http_port = http_port or get_free_port()
        self.ws_port = ws_port or get_free_port()

        self.state = "idle"
        self.audio_level = 0.0

        self.http_server: Optional[ThreadingHTTPServer] = None
        self.http_thread: Optional[threading.Thread] = None

        self.ws_server = None
        self.ws_thread: Optional[threading.Thread] = None
        self.ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self.connected_clients: Set = set()

        self.preview_process: Optional[subprocess.Popen] = None
        self.temp_profile_dir: Optional[str] = None
        self.is_running = False

    def start_servers(self) -> None:
        """Запускает локальный статический HTTP и WebSocket серверы в фоновых потоках."""
        if self.is_running:
            return

        # 1. HTTP Server
        def make_handler(*args, **kwargs):
            return AkakiyStaticHTTPHandler(*args, directory=self.assets_dir, **kwargs)

        self.http_server = ThreadingHTTPServer(("127.0.0.1", self.http_port), make_handler)
        self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.http_thread.start()

        # 2. WebSocket Server (если доступен websockets)
        if websockets:
            self.ws_thread = threading.Thread(target=self._run_ws_loop, daemon=True)
            self.ws_thread.start()

        self.is_running = True

    def _run_ws_loop(self) -> None:
        """Асинхронный цикл для приёма WebSocket-подключений."""
        self.ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.ws_loop)

        async def handler(websocket):
            self.connected_clients.add(websocket)
            # Отправка текущего начального состояния
            init_msg = json.dumps({"action": "setState", "state": self.state})
            try:
                await websocket.send(init_msg)
                async for _ in websocket:
                    pass
            except Exception:
                pass
            finally:
                self.connected_clients.discard(websocket)

        async def main():
            self._ws_stop_event = asyncio.Event()
            async with websockets.serve(handler, "127.0.0.1", self.ws_port):
                await self._ws_stop_event.wait()

        try:
            self.ws_loop.run_until_complete(main())
        except Exception:
            pass
        finally:
            try:
                pending = asyncio.all_tasks(self.ws_loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self.ws_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                self.ws_loop.close()
            except Exception:
                pass

    def broadcast_message(self, data: dict) -> None:
        """Рассылает сообщение всем подключенным WebGL-клиентам."""
        if not self.ws_loop or not self.connected_clients:
            return

        msg_str = json.dumps(data)

        async def _send_all():
            for ws in list(self.connected_clients):
                try:
                    await ws.send(msg_str)
                except Exception:
                    self.connected_clients.discard(ws)

        asyncio.run_coroutine_threadsafe(_send_all(), self.ws_loop)

    def set_state(self, new_state: str) -> None:
        """Переключает состояние ядра и уведомляет WebGL шейдер."""
        if new_state in self.VALID_STATES:
            self.state = new_state
            self.broadcast_message({"action": "setState", "state": new_state})

    def set_audio_level(self, level: float) -> None:
        """Передаёт текущий уровень громкости аудиопотока (0.0 .. 1.0)."""
        clamped = max(0.0, min(1.0, float(level)))
        self.audio_level = clamped
        self.broadcast_message({"action": "setAudioLevel", "level": clamped})

    def launch_preview(self, width: int = 1000, height: int = 720, embedded: bool = False) -> Optional[subprocess.Popen]:
        """
        Запускает отдельное тестовое окно в режиме App (без адресной строки и вкладок)
        для визуальной оценки и калибровки. При embedded=True калибровочный HUD скрывается.
        """
        self.start_servers()
        time.sleep(0.15)  # Небольшая пауза для биндинга портов

        edge_bin = find_edge_binary()
        embed_param = "&embedded=1" if embedded else ""
        if not edge_bin:
            import webbrowser
            url = f"http://127.0.0.1:{self.http_port}/?ws={self.ws_port}{embed_param}"
            webbrowser.open(url)
            return None

        self.temp_profile_dir = tempfile.mkdtemp(prefix="akakiy_core_preview_")
        url = f"http://127.0.0.1:{self.http_port}/?ws={self.ws_port}{embed_param}"

        cmd = [
            edge_bin,
            f"--app={url}",
            f"--window-size={width},{height}",
            f"--user-data-dir={self.temp_profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate,OptimizationHints",
            "--enable-gpu-rasterization",
            "--enable-zero-copy",
        ]

        self.preview_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return self.preview_process

    def stop(self) -> None:
        """Останавливает серверы, завершает дочерний процесс и удаляет временный профиль."""
        if self.preview_process:
            try:
                self.preview_process.terminate()
                self.preview_process.wait(timeout=1.5)
            except Exception:
                try:
                    self.preview_process.kill()
                except Exception:
                    pass
            self.preview_process = None

        if self.http_server:
            try:
                self.http_server.shutdown()
                self.http_server.server_close()
            except Exception:
                pass
            self.http_server = None

        if self.ws_loop and hasattr(self, "_ws_stop_event") and self._ws_stop_event:
            try:
                self.ws_loop.call_soon_threadsafe(self._ws_stop_event.set)
            except Exception:
                pass

        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=1.0)
        self.ws_loop = None
        self.ws_thread = None

        if self.temp_profile_dir and os.path.exists(self.temp_profile_dir):
            try:
                shutil.rmtree(self.temp_profile_dir, ignore_errors=True)
            except Exception:
                pass
            self.temp_profile_dir = None

        self.is_running = False

    def __del__(self):
        self.stop()


