#!/usr/bin/env python3
"""Linux sensor dashboard and HID telemetry bridge for the extracted Rise Mode app."""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

VID = 0xAA88
PID = 0x8666
PACKET_SIZE = 24
ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "static" / "index.html"


def read_text(path: str | Path) -> str | None:
    try:
        return Path(path).read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None


def hwmon_sensors() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    temperatures: list[dict[str, Any]] = []
    fans: list[dict[str, Any]] = []
    for directory in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        hw_name = read_text(Path(directory) / "name") or Path(directory).name
        for path in sorted(glob.glob(f"{directory}/temp*_input")):
            raw = read_text(path)
            if raw is None:
                continue
            try:
                value = float(raw) / 1000.0
            except ValueError:
                continue
            if not -20 <= value <= 150:
                continue
            index = Path(path).name.removesuffix("_input")
            label = read_text(Path(directory) / f"{index}_label") or index
            temperatures.append({
                "name": f"{hw_name} · {label}",
                "label": label,
                "source": hw_name.lower(),
                "celsius": round(value, 1),
            })
        for path in sorted(glob.glob(f"{directory}/fan*_input")):
            raw = read_text(path)
            if raw is None:
                continue
            try:
                rpm = int(raw)
            except ValueError:
                continue
            index = Path(path).name.removesuffix("_input")
            label = read_text(Path(directory) / f"{index}_label") or index
            fans.append({"name": f"{hw_name} · {label}", "rpm": rpm})
    return temperatures, fans


def choose_temperature(items: list[dict[str, Any]], role: str) -> float | None:
    if role == "cpu":
        patterns = ("package", "tctl", "tdie", "cpu", "coretemp", "k10temp", "zenpower")
        excluded = ("gpu", "nvidia", "amdgpu")
    elif role == "gpu":
        patterns = ("gpu", "nvidia", "amdgpu", "radeon")
        excluded = ()
    else:
        patterns = ("motherboard", "mainboard", "system", "ambient", "board")
        excluded = ("cpu", "coretemp", "k10temp", "zenpower", "gpu", "nvidia", "amdgpu")

    for item in items:
        identity = f"{item['source']} {item['label']}".lower()
        if not any(word in identity for word in excluded) and any(word in identity for word in patterns):
            return item["celsius"]
    if role == "board":
        for item in items:
            identity = f"{item['source']} {item['label']}".lower()
            if not any(word in identity for word in excluded):
                return item["celsius"]
    return None


class CpuLoad:
    def __init__(self) -> None:
        self.previous: tuple[int, int] | None = None

    def read(self) -> int | None:
        line = read_text("/proc/stat")
        if not line:
            return None
        first = line.splitlines()[0].split()
        if not first or first[0] != "cpu":
            return None
        try:
            values = [int(value) for value in first[1:]]
        except ValueError:
            return None
        if len(values) < 4:
            return None
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        current = (total, idle)
        previous, self.previous = self.previous, current
        if previous is None:
            return 0
        total_delta = total - previous[0]
        idle_delta = idle - previous[1]
        if total_delta <= 0:
            return 0
        return max(0, min(100, round((total_delta - idle_delta) * 100 / total_delta)))


def memory_load() -> int | None:
    contents = read_text("/proc/meminfo")
    if not contents:
        return None
    values: dict[str, int] = {}
    for line in contents.splitlines():
        match = re.match(r"^(MemTotal|MemAvailable):\s+(\d+)", line)
        if match:
            values[match.group(1)] = int(match.group(2))
    total, available = values.get("MemTotal"), values.get("MemAvailable")
    if not total or available is None:
        return None
    return max(0, min(100, round((total - available) * 100 / total)))


def gpu_load() -> int | None:
    for path in sorted(glob.glob("/sys/class/drm/card[0-9]*/device/gpu_busy_percent")):
        raw = read_text(path)
        try:
            return max(0, min(100, int(raw))) if raw is not None else None
        except ValueError:
            continue
    return None


def nvidia_gpu_temperature() -> tuple[float | None, str | None]:
    """Read NVIDIA's current core temperature when its kernel driver is available."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip() or "nvidia-smi falhou"
    try:
        value = float(result.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None, "nvidia-smi não retornou temperatura"
    if not 0 <= value <= 125:
        return None, f"temperatura NVIDIA fora da faixa: {value:g} °C"
    return value, None


class TemperatureFilter:
    """Require repeated readings before accepting a large single-sample jump."""

    def __init__(self, jump_threshold: float = 25, confirm_count: int = 3, max_age: float = 10) -> None:
        self.jump_threshold = jump_threshold
        self.confirm_count = confirm_count
        self.max_age = max_age
        self.stable: float | None = None
        self.last_valid_at = 0.0
        self.candidate: float | None = None
        self.candidate_count = 0

    def update(self, value: float | None, now: float) -> float | None:
        if value is None:
            return self.stable if now - self.last_valid_at <= self.max_age else None
        if not 0 <= value <= 125:
            return self.stable if now - self.last_valid_at <= self.max_age else None

        needs_confirmation = self.stable is None or abs(value - self.stable) >= self.jump_threshold
        if needs_confirmation:
            if self.candidate is not None and abs(value - self.candidate) <= 2:
                self.candidate_count += 1
            else:
                self.candidate = value
                self.candidate_count = 1
            if self.candidate_count < self.confirm_count:
                return self.stable if now - self.last_valid_at <= self.max_age else None
            value = self.candidate

        self.stable = value
        self.last_valid_at = now
        self.candidate = None
        self.candidate_count = 0
        return value


class HidBridge:
    def __init__(self) -> None:
        self.devices: list[tuple[int, str]] = []
        self.last_scan = 0.0
        self.error: str | None = None
        self.device_names: list[str] = []

    def scan(self) -> None:
        if time.monotonic() - self.last_scan < 5:
            return
        self.last_scan = time.monotonic()
        self.close()
        access_errors: list[str] = []
        for sys_path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
            hid_name = Path(sys_path).name
            try:
                resolved = (Path(sys_path) / "device").resolve(strict=True)
            except OSError:
                continue
            usb_device = None
            for parent in (resolved, *resolved.parents):
                vendor = read_text(parent / "idVendor")
                product_id = read_text(parent / "idProduct")
                if vendor and product_id:
                    if vendor.lower() == f"{VID:04x}" and product_id.lower() == f"{PID:04x}":
                        usb_device = parent
                    break
            if usb_device is None:
                continue
            try:
                product = (usb_device / "product").read_text(encoding="utf-8").strip() or "Rise Mode HID"
            except (OSError, UnicodeError):
                product = "Rise Mode HID"
            try:
                fd = os.open(f"/dev/{hid_name}", os.O_WRONLY | os.O_NONBLOCK)
                self.devices.append((fd, product))
            except OSError as exc:
                access_errors.append(f"{hid_name}: {exc.strerror}")
        self.device_names = [name for _, name in self.devices]
        if self.devices:
            self.error = None
        elif access_errors:
            self.error = "Sem acesso ao HID; confira a regra udev: " + ", ".join(access_errors)
        else:
            self.error = "dispositivo AA88:8666 não encontrado"

    def close(self) -> None:
        for fd, _ in self.devices:
            try:
                os.close(fd)
            except OSError:
                pass
        self.devices.clear()

    @staticmethod
    def make_packet(state: dict[str, Any]) -> bytes:
        # Positions confirmed in MainForm.Timer_Tick of the supplied executable.
        fields = (
            state.get("cpu_temp"),
            state.get("gpu_temp"),
            state.get("cpu_load"),
            state.get("memory_load"),
            state.get("board_temp"),
            state.get("gpu_load"),
        )
        payload = bytearray(PACKET_SIZE)
        payload[0] = 0  # HID report ID, as in the Windows implementation
        for index, value in enumerate(fields, start=1):
            if value is not None:
                payload[index] = max(0, min(255, int(value)))
        return bytes(payload)

    def send(self, packet: bytes | None) -> None:
        self.scan()
        if packet is None or not self.devices:
            return
        errors: list[str] = []
        failed: list[tuple[int, str]] = []
        for fd, name in list(self.devices):
            try:
                written = os.write(fd, packet)
                if written != len(packet):
                    raise OSError(f"escritos {written} de {len(packet)} bytes")
            except OSError as exc:
                errors.append(f"{name}: {exc}")
                failed.append((fd, name))
        if errors:
            for fd, _ in failed:
                try:
                    os.close(fd)
                except OSError:
                    pass
            self.devices = [entry for entry in self.devices if entry not in failed]
            self.device_names = [name for _, name in self.devices]
            self.error = "; ".join(errors)


class Monitor:
    def __init__(self) -> None:
        self.cpu = CpuLoad()
        self.hid = HidBridge()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.state: dict[str, Any] = {"updated_at": None}
        self.last_logged_status: tuple[Any, ...] | None = None
        self.temperature_filters = {
            "cpu": TemperatureFilter(),
            "gpu": TemperatureFilter(),
            "board": TemperatureFilter(),
        }
        self.nvidia_checked_at = 0.0
        self.nvidia_cached_value: float | None = None
        self.nvidia_cached_error: str | None = None
        self.last_cpu_spike_log = 0.0
        self.thread = threading.Thread(target=self.run, name="sensor-monitor", daemon=True)

    def read_nvidia_temperature(self, now: float) -> tuple[float | None, str | None]:
        if now - self.nvidia_checked_at >= 5:
            self.nvidia_cached_value, self.nvidia_cached_error = nvidia_gpu_temperature()
            self.nvidia_checked_at = now
        return self.nvidia_cached_value, self.nvidia_cached_error

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        temperatures, fans = hwmon_sensors()
        cpu_raw = choose_temperature(temperatures, "cpu")
        gpu_raw = choose_temperature(temperatures, "gpu")
        gpu_source = "hwmon" if gpu_raw is not None else None
        gpu_error = None
        if gpu_raw is None:
            gpu_raw, gpu_error = self.read_nvidia_temperature(now)
            if gpu_raw is not None:
                gpu_source = "nvidia-smi"
        board_raw = choose_temperature(temperatures, "board")
        cpu_stable_before = self.temperature_filters["cpu"].stable
        cpu_filtered = self.temperature_filters["cpu"].update(cpu_raw, now)
        if (
            cpu_raw is not None
            and cpu_stable_before is not None
            and abs(cpu_raw - cpu_stable_before) >= self.temperature_filters["cpu"].jump_threshold
            and now - self.last_cpu_spike_log >= 10
        ):
            sent_value = int(cpu_filtered) if cpu_filtered is not None else None
            print(
                f"[{time.strftime('%H:%M:%S')}] CPU: leitura bruta {cpu_raw:.1f} °C; "
                f"estável {cpu_stable_before:.1f} °C; valor enviado ao HID {sent_value}",
                flush=True,
            )
            self.last_cpu_spike_log = now
        state = {
            "cpu_temp": cpu_filtered,
            "gpu_temp": self.temperature_filters["gpu"].update(gpu_raw, now),
            "board_temp": self.temperature_filters["board"].update(board_raw, now),
            "gpu_temp_source": gpu_source,
            "gpu_temp_error": gpu_error,
            "cpu_load": self.cpu.read(),
            "memory_load": memory_load(),
            "gpu_load": gpu_load(),
            "temperatures": temperatures,
            "fans": fans,
            "updated_at": time.strftime("%H:%M:%S"),
        }
        # The cooler's CPU display uses byte 1. A missing GPU sensor must not
        # prevent CPU temperature updates; byte 2 remains zero when unavailable.
        packet = self.hid.make_packet(state) if state["cpu_temp"] is not None else None
        self.hid.scan()
        self.hid.send(packet)
        if packet is None and self.hid.devices:
            hid_message = "temperatura da CPU indisponível ou instável; envio pausado"
        elif self.hid.error:
            hid_message = self.hid.error
        else:
            hid_message = "telemetria HID ativa; temperatura da CPU enviada"
            if gpu_error:
                hid_message += "; GPU indisponível (não afeta a leitura da CPU)"
        state["hid"] = {
            "connected": bool(self.hid.devices),
            "devices": self.hid.device_names,
            "message": hid_message,
            "vid": f"{VID:04X}",
            "pid": f"{PID:04X}",
            "packet_hex": packet.hex(" ") if packet is not None else None,
        }
        return state

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                state = self.snapshot()
                hid_state = state.get("hid", {})
                status = (hid_state.get("connected"), hid_state.get("message"), tuple(hid_state.get("devices", [])))
                if status != self.last_logged_status:
                    label = hid_state.get("message") or ", ".join(hid_state.get("devices", [])) or "HID indisponível"
                    print(f"[{time.strftime('%H:%M:%S')}] HID: {label}", flush=True)
                    self.last_logged_status = status
                with self.lock:
                    self.state = state
            except Exception as exc:
                print(f"[{time.strftime('%H:%M:%S')}] Erro ao ler sensores/HID: {exc}", flush=True)
                with self.lock:
                    self.state = {"updated_at": time.strftime("%H:%M:%S"), "error": str(exc)}
            self.stop.wait(0.25)

    def start(self) -> None:
        self.thread.start()

    def get_state(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.state)


def handler_for(monitor: Monitor) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler API
            if self.path == "/api/state":
                body = json.dumps(monitor.get_state(), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
            elif self.path == "/" or self.path == "/index.html":
                body = INDEX.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
            else:
                body = b"Not Found"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[{self.log_date_time_string()}] {fmt % args}")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Rise Mode CPU telemetry dashboard for Linux")
    parser.add_argument("--host", default="127.0.0.1", help="interface de escuta (padrão: 127.0.0.1)")
    parser.add_argument("--port", default=8765, type=int, help="porta HTTP (padrão: 8765)")
    parser.add_argument("--no-web", action="store_true", help="executa somente o serviço de telemetria HID")
    args = parser.parse_args()

    monitor = Monitor()
    monitor.start()
    if args.no_web:
        print("Serviço de telemetria iniciado em segundo plano pelo systemd.", flush=True)
        try:
            monitor.thread.join()
        except KeyboardInterrupt:
            pass
        finally:
            monitor.stop.set()
            monitor.hid.close()
        return

    server = ThreadingHTTPServer((args.host, args.port), handler_for(monitor))
    print(f"Painel Rise Mode Linux: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        monitor.stop.set()
        monitor.hid.close()
        server.server_close()


if __name__ == "__main__":
    main()
