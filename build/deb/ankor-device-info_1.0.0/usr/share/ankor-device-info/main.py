from __future__ import annotations

import os
import platform
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

import psutil

try:
    from PySide6.QtCore import QPoint, QSettings, QTimer, Qt
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QProgressBar,
        QVBoxLayout,
        QWidget,
    )

    QT_BINDING = "PySide6"
except ImportError:
    try:
        from PyQt6.QtCore import QPoint, QSettings, QTimer, Qt
        from PyQt6.QtWidgets import (
            QApplication,
            QCheckBox,
            QGridLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QMainWindow,
            QProgressBar,
            QVBoxLayout,
            QWidget,
        )

        QT_BINDING = "PyQt6"
    except ImportError as exc:
        raise SystemExit(
            "PySide6 or PyQt6 is required.\n"
            "Install one of them:\n"
            "  pip install PySide6\n"
            "or\n"
            "  pip install PyQt6"
        ) from exc


@dataclass
class Snapshot:
    cpu_usage_percent: float
    cpu_frequency_mhz: Optional[float]
    cpu_temp_c: Optional[float]
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    swap_percent: float
    disk_percent: float
    disk_mount: str
    uptime: str
    net_download_bytes_per_sec: float
    net_upload_bytes_per_sec: float
    gpu_name: Optional[str]
    gpu_usage_percent: Optional[float]
    gpu_temp_c: Optional[float]


class NvidiaMonitor:
    def __init__(self) -> None:
        self.available = False
        self.name: Optional[str] = None
        self._handle = None
        self._nvml = None
        self._initialize()

    def _initialize(self) -> None:
        try:
            import pynvml
        except ImportError:
            return

        try:
            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.name = pynvml.nvmlDeviceGetName(self._handle)
            if isinstance(self.name, bytes):
                self.name = self.name.decode("utf-8", errors="replace")
            self.available = True
        except Exception:
            self.available = False

    def read(self) -> tuple[Optional[float], Optional[float]]:
        if not self.available or self._nvml is None or self._handle is None:
            return None, None

        try:
            util = self._nvml.nvmlDeviceGetUtilizationRates(self._handle).gpu
            temp = self._nvml.nvmlDeviceGetTemperature(
                self._handle, self._nvml.NVML_TEMPERATURE_GPU
            )
            return float(util), float(temp)
        except Exception:
            return None, None

    def shutdown(self) -> None:
        if not self.available or self._nvml is None:
            return
        try:
            self._nvml.nvmlShutdown()
        except Exception:
            pass
        self.available = False


class SystemSampler:
    def __init__(self) -> None:
        self._last_net = psutil.net_io_counters()
        self._last_time = time.monotonic()
        self._nvidia = NvidiaMonitor()
        self._disk_mount = self._detect_disk_mount()
        psutil.cpu_percent(interval=None)

    def sample(self) -> Snapshot:
        cpu_usage_percent = psutil.cpu_percent(interval=None)
        cpu_frequency_mhz = self._read_cpu_frequency()
        cpu_temp_c = self._read_cpu_temperature()

        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        disk = self._read_disk_usage()

        now_net = psutil.net_io_counters()
        now_time = time.monotonic()
        elapsed = max(now_time - self._last_time, 1e-6)
        download_per_sec = (now_net.bytes_recv - self._last_net.bytes_recv) / elapsed
        upload_per_sec = (now_net.bytes_sent - self._last_net.bytes_sent) / elapsed
        self._last_net = now_net
        self._last_time = now_time

        uptime_seconds = max(0, int(time.time() - psutil.boot_time()))
        uptime = str(timedelta(seconds=uptime_seconds))
        gpu_usage, gpu_temp = self._nvidia.read()

        return Snapshot(
            cpu_usage_percent=cpu_usage_percent,
            cpu_frequency_mhz=cpu_frequency_mhz,
            cpu_temp_c=cpu_temp_c,
            ram_percent=vm.percent,
            ram_used_gb=self._to_gb(vm.used),
            ram_total_gb=self._to_gb(vm.total),
            swap_percent=sm.percent,
            disk_percent=disk.percent,
            disk_mount=self._disk_mount,
            uptime=uptime,
            net_download_bytes_per_sec=max(download_per_sec, 0.0),
            net_upload_bytes_per_sec=max(upload_per_sec, 0.0),
            gpu_name=self._nvidia.name,
            gpu_usage_percent=gpu_usage,
            gpu_temp_c=gpu_temp,
        )

    def shutdown(self) -> None:
        self._nvidia.shutdown()

    def _read_disk_usage(self):
        try:
            return psutil.disk_usage(self._disk_mount)
        except Exception:
            return psutil.disk_usage("/")

    @staticmethod
    def _detect_disk_mount() -> str:
        if platform.system().lower().startswith("win"):
            system_drive = os.environ.get("SystemDrive", "C:")
            if not system_drive.endswith("\\"):
                system_drive = f"{system_drive}\\"
            return system_drive
        return "/"

    @staticmethod
    def _to_gb(value: float) -> float:
        return value / (1024 ** 3)

    @staticmethod
    def _read_cpu_frequency() -> Optional[float]:
        try:
            freq = psutil.cpu_freq()
            if freq is None:
                return None
            return float(freq.current)
        except Exception:
            return None

    @staticmethod
    def _read_cpu_temperature() -> Optional[float]:
        if not hasattr(psutil, "sensors_temperatures"):
            return None

        try:
            sensor_map = psutil.sensors_temperatures(fahrenheit=False) or {}
        except Exception:
            return None

        if not sensor_map:
            return None

        preferred_keys = ("coretemp", "k10temp", "cpu_thermal", "acpitz")
        for key in preferred_keys:
            entries = sensor_map.get(key, [])
            values = [entry.current for entry in entries if entry.current is not None]
            if values:
                return max(values)

        any_values = []
        for entries in sensor_map.values():
            any_values.extend(entry.current for entry in entries if entry.current is not None)
        return max(any_values) if any_values else None


class OverlayWindow(QWidget):
    def __init__(self, on_position_changed: Optional[Callable[[QPoint], None]] = None) -> None:
        super().__init__(None)
        self.setObjectName("OverlayWindow")
        self.setWindowTitle("Pinned Metrics")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setFixedSize(390, 132)
        self.setWindowOpacity(0.96)

        self._drag_offset: Optional[QPoint] = None
        self._on_position_changed = on_position_changed
        self._dark_mode = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        self.header_label = QLabel("PINNED HARDWARE METRICS")
        self.header_label.setObjectName("OverlayHeader")
        layout.addWidget(self.header_label)

        self.cpu_gpu_temp_label = QLabel("CPU Temp: N/A | GPU Temp: N/A")
        self.cpu_gpu_temp_label.setObjectName("OverlayMetric")
        layout.addWidget(self.cpu_gpu_temp_label)

        self.ram_usage_label = QLabel("RAM: N/A")
        self.ram_usage_label.setObjectName("OverlayMetric")
        layout.addWidget(self.ram_usage_label)

        self.hint_label = QLabel("Left drag to move")
        self.hint_label.setObjectName("OverlayHint")
        layout.addWidget(self.hint_label)

        self.apply_theme(dark_mode=True)

    def apply_theme(self, dark_mode: bool) -> None:
        self._dark_mode = dark_mode
        if dark_mode:
            self.setStyleSheet(
                """
                QWidget#OverlayWindow {
                    background: #0f172a;
                    border: 1px solid #334155;
                    border-radius: 12px;
                }
                QLabel#OverlayHeader {
                    color: #7dd3fc;
                    font-size: 11px;
                    font-weight: 700;
                }
                QLabel#OverlayMetric {
                    color: #f8fafc;
                    font-size: 16px;
                    font-weight: 700;
                }
                QLabel#OverlayHint {
                    color: #94a3b8;
                    font-size: 11px;
                }
                """
            )
            return

        self.setStyleSheet(
            """
            QWidget#OverlayWindow {
                background: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 12px;
            }
            QLabel#OverlayHeader {
                color: #0369a1;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#OverlayMetric {
                color: #0f172a;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#OverlayHint {
                color: #64748b;
                font-size: 11px;
            }
            """
        )

    def update_metrics(self, snapshot: Snapshot) -> None:
        cpu_temp = f"{snapshot.cpu_temp_c:.1f} C" if snapshot.cpu_temp_c is not None else "N/A"
        gpu_temp = f"{snapshot.gpu_temp_c:.1f} C" if snapshot.gpu_temp_c is not None else "N/A"
        self.cpu_gpu_temp_label.setText(f"CPU Temp: {cpu_temp} | GPU Temp: {gpu_temp}")
        self.ram_usage_label.setText(
            f"RAM: {snapshot.ram_percent:.1f}% ({snapshot.ram_used_gb:.1f}/{snapshot.ram_total_gb:.1f} GB)"
        )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_offset and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def moveEvent(self, event) -> None:  # type: ignore[override]
        if self._on_position_changed is not None:
            self._on_position_changed(self.pos())
        super().moveEvent(event)


class MonitorWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("Ankor", "DeviceInfoMonitor")
        self.dark_mode = self._as_bool(self.settings.value("ui/dark_mode", True), True)
        self.overlay_enabled = self._as_bool(self.settings.value("overlay/enabled", False), False)

        self.setWindowTitle("System Hardware Monitor")
        self.resize(980, 660)

        self.sampler = SystemSampler()
        self.overlay_window = OverlayWindow(on_position_changed=self._save_overlay_position)
        self._build_ui()
        self._restore_main_window_geometry()
        self._restore_overlay_position()

        self._apply_theme(self.dark_mode)
        self._update_overlay_chip(self.overlay_enabled)

        if self.overlay_enabled:
            self._toggle_overlay_window(True)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh_metrics)
        self.timer.start()
        self.refresh_metrics()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("RootWidget")
        self.setCentralWidget(root)

        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(12)

        header_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)

        title = QLabel("Hardware Monitor")
        title.setObjectName("AppTitle")
        title_column.addWidget(title)

        subtitle = QLabel(f"{platform.system()} | {platform.release()} | {QT_BINDING}")
        subtitle.setObjectName("AppSubtitle")
        title_column.addWidget(subtitle)
        header_row.addLayout(title_column)
        header_row.addStretch(1)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        self.overlay_toggle = QCheckBox("Pinned Overlay")
        self.overlay_toggle.setChecked(self.overlay_enabled)
        self.overlay_toggle.toggled.connect(self._toggle_overlay_window)
        controls.addWidget(self.overlay_toggle)

        self.theme_toggle = QCheckBox("Dark Theme")
        self.theme_toggle.setChecked(self.dark_mode)
        self.theme_toggle.toggled.connect(self._toggle_theme)
        controls.addWidget(self.theme_toggle)
        header_row.addLayout(controls)
        main_layout.addLayout(header_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.overlay_chip = QLabel("Overlay: OFF")
        self.overlay_chip.setObjectName("StatusChip")
        status_row.addWidget(self.overlay_chip)

        self.last_update_chip = QLabel("Updated: --:--:--")
        self.last_update_chip.setObjectName("StatusChip")
        status_row.addWidget(self.last_update_chip)
        status_row.addStretch(1)
        main_layout.addLayout(status_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        main_layout.addLayout(grid)

        self.cpu_label, self.cpu_bar = self._metric_card(grid, 0, 0, "CPU Usage", with_bar=True)
        self.cpu_temp_label, self.cpu_temp_bar = self._metric_card(
            grid, 0, 1, "CPU Temperature", with_bar=True, bar_max=120
        )
        self.ram_label, self.ram_bar = self._metric_card(grid, 1, 0, "RAM Usage", with_bar=True)
        self.swap_label, self.swap_bar = self._metric_card(grid, 1, 1, "Swap Usage", with_bar=True)
        self.disk_label, self.disk_bar = self._metric_card(grid, 2, 0, "Disk Usage", with_bar=True)
        self.gpu_label, self.gpu_bar = self._metric_card(grid, 2, 1, "GPU Usage", with_bar=True)
        self.network_label, _ = self._metric_card(grid, 3, 0, "Network", with_bar=False)
        self.uptime_label, _ = self._metric_card(grid, 3, 1, "Uptime", with_bar=False)

    def _metric_card(
        self,
        grid: QGridLayout,
        row: int,
        column: int,
        title: str,
        with_bar: bool,
        bar_max: int = 100,
    ) -> tuple[QLabel, Optional[QProgressBar]]:
        card = QGroupBox(title)
        card.setObjectName("MetricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 18, 12, 12)
        layout.setSpacing(8)

        value_label = QLabel("N/A")
        value_label.setObjectName("MetricValue")
        layout.addWidget(value_label)

        bar = None
        if with_bar:
            bar = QProgressBar()
            bar.setRange(0, bar_max)
            bar.setValue(0)
            layout.addWidget(bar)

        grid.addWidget(card, row, column)
        return value_label, bar

    def refresh_metrics(self) -> None:
        snapshot = self.sampler.sample()

        self.cpu_label.setText(
            f"{snapshot.cpu_usage_percent:.1f}%"
            + (
                f" @ {snapshot.cpu_frequency_mhz:.0f} MHz"
                if snapshot.cpu_frequency_mhz is not None
                else ""
            )
        )
        self._set_progress(self.cpu_bar, snapshot.cpu_usage_percent)

        if snapshot.cpu_temp_c is None:
            self.cpu_temp_label.setText("N/A (not exposed by system)")
            self._set_progress(self.cpu_temp_bar, 0.0)
        else:
            self.cpu_temp_label.setText(f"{snapshot.cpu_temp_c:.1f} C")
            self._set_progress(self.cpu_temp_bar, snapshot.cpu_temp_c)

        self.ram_label.setText(
            f"{snapshot.ram_percent:.1f}% ({snapshot.ram_used_gb:.1f} / {snapshot.ram_total_gb:.1f} GB)"
        )
        self._set_progress(self.ram_bar, snapshot.ram_percent)

        self.swap_label.setText(f"{snapshot.swap_percent:.1f}%")
        self._set_progress(self.swap_bar, snapshot.swap_percent)

        self.disk_label.setText(f"{snapshot.disk_mount}: {snapshot.disk_percent:.1f}%")
        self._set_progress(self.disk_bar, snapshot.disk_percent)

        if snapshot.gpu_usage_percent is None:
            self.gpu_label.setText("N/A (install pynvml + NVIDIA driver)")
            self._set_progress(self.gpu_bar, 0.0)
        else:
            gpu_header = snapshot.gpu_name or "GPU"
            temp_text = (
                f" | {snapshot.gpu_temp_c:.1f} C" if snapshot.gpu_temp_c is not None else ""
            )
            self.gpu_label.setText(f"{gpu_header}: {snapshot.gpu_usage_percent:.1f}%{temp_text}")
            self._set_progress(self.gpu_bar, snapshot.gpu_usage_percent)

        self.network_label.setText(
            f"Download: {self._format_rate(snapshot.net_download_bytes_per_sec)}\n"
            f"Upload: {self._format_rate(snapshot.net_upload_bytes_per_sec)}"
        )
        self.uptime_label.setText(snapshot.uptime)

        self.last_update_chip.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
        self.overlay_window.update_metrics(snapshot)

    def _toggle_theme(self, enabled: bool) -> None:
        self.dark_mode = enabled
        self.settings.setValue("ui/dark_mode", enabled)
        self._apply_theme(enabled)

    def _toggle_overlay_window(self, enabled: bool) -> None:
        self.overlay_enabled = enabled
        self.settings.setValue("overlay/enabled", enabled)
        self._update_overlay_chip(enabled)
        if enabled:
            if self.overlay_window.pos().isNull():
                self._position_overlay_window()
            self.overlay_window.show()
            self.overlay_window.raise_()
            return
        self.overlay_window.hide()

    def _update_overlay_chip(self, enabled: bool) -> None:
        self.overlay_chip.setText("Overlay: ON" if enabled else "Overlay: OFF")

    def _restore_main_window_geometry(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry is None:
            return
        try:
            self.restoreGeometry(geometry)
        except Exception:
            pass

    def _restore_overlay_position(self) -> None:
        position = self.settings.value("overlay/position")
        if isinstance(position, QPoint):
            self.overlay_window.move(position)

    def _save_overlay_position(self, position: QPoint) -> None:
        self.settings.setValue("overlay/position", position)

    def _position_overlay_window(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            x = available.right() - self.overlay_window.width() - 20
            y = available.top() + 30
            self.overlay_window.move(max(available.left(), x), max(available.top(), y))
            return
        self.overlay_window.move(40, 40)

    def _apply_theme(self, dark_mode: bool) -> None:
        if dark_mode:
            self.setStyleSheet(
                """
                QWidget#RootWidget {
                    background: qlineargradient(
                        x1: 0, y1: 0, x2: 1, y2: 1,
                        stop: 0 #0b1220, stop: 1 #131c31
                    );
                    color: #e2e8f0;
                    font-size: 14px;
                    font-family: "Segoe UI", "Noto Sans", sans-serif;
                }
                QLabel#AppTitle {
                    color: #f8fafc;
                    font-size: 32px;
                    font-weight: 700;
                }
                QLabel#AppSubtitle {
                    color: #93c5fd;
                    font-size: 13px;
                    font-weight: 600;
                }
                QLabel#StatusChip {
                    background: #17233a;
                    border: 1px solid #2c3b57;
                    border-radius: 10px;
                    padding: 6px 10px;
                    color: #cbd5e1;
                    font-size: 12px;
                }
                QCheckBox {
                    color: #cbd5e1;
                    font-size: 13px;
                    font-weight: 600;
                    spacing: 8px;
                }
                QCheckBox::indicator {
                    width: 38px;
                    height: 20px;
                    border-radius: 10px;
                    border: 1px solid #334155;
                    background: #1f2937;
                }
                QCheckBox::indicator:checked {
                    border: 1px solid #38bdf8;
                    background: #0ea5e9;
                }
                QGroupBox#MetricCard {
                    border: 1px solid #243244;
                    border-radius: 12px;
                    margin-top: 10px;
                    padding-top: 6px;
                    background: rgba(15, 23, 42, 0.78);
                    font-weight: 700;
                    color: #e2e8f0;
                }
                QGroupBox#MetricCard::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 2px 5px;
                    color: #7dd3fc;
                }
                QLabel#MetricValue {
                    font-size: 19px;
                    font-weight: 700;
                    color: #f8fafc;
                }
                """
            )
            self.overlay_window.apply_theme(dark_mode=True)
            return

        self.setStyleSheet(
            """
            QWidget#RootWidget {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #f8fafc, stop: 1 #e2e8f0
                );
                color: #0f172a;
                font-size: 14px;
                font-family: "Segoe UI", "Noto Sans", sans-serif;
            }
            QLabel#AppTitle {
                color: #0f172a;
                font-size: 32px;
                font-weight: 700;
            }
            QLabel#AppSubtitle {
                color: #0369a1;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#StatusChip {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 10px;
                padding: 6px 10px;
                color: #1e293b;
                font-size: 12px;
            }
            QCheckBox {
                color: #334155;
                font-size: 13px;
                font-weight: 600;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 38px;
                height: 20px;
                border-radius: 10px;
                border: 1px solid #cbd5e1;
                background: #e2e8f0;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #0284c7;
                background: #38bdf8;
            }
            QGroupBox#MetricCard {
                border: 1px solid #cbd5e1;
                border-radius: 12px;
                margin-top: 10px;
                padding-top: 6px;
                background: rgba(255, 255, 255, 0.9);
                font-weight: 700;
                color: #0f172a;
            }
            QGroupBox#MetricCard::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 2px 5px;
                color: #0369a1;
            }
            QLabel#MetricValue {
                font-size: 19px;
                font-weight: 700;
                color: #0f172a;
            }
            """
        )
        self.overlay_window.apply_theme(dark_mode=False)

    def _set_progress(self, bar: Optional[QProgressBar], value: float) -> None:
        if bar is None:
            return

        bounded = max(bar.minimum(), min(bar.maximum(), int(round(value))))
        bar.setValue(bounded)

        track = "#0f172a" if self.dark_mode else "#e2e8f0"
        border = "#334155" if self.dark_mode else "#cbd5e1"
        text = "#e2e8f0" if self.dark_mode else "#0f172a"
        chunk = self._progress_color(value)

        bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: 1px solid {border};
                border-radius: 8px;
                text-align: center;
                min-height: 18px;
                background: {track};
                color: {text};
                font-size: 12px;
                font-weight: 700;
            }}
            QProgressBar::chunk {{
                border-radius: 7px;
                background: {chunk};
            }}
            """
        )

    @staticmethod
    def _progress_color(value: float) -> str:
        if value >= 90:
            return "#f43f5e"
        if value >= 75:
            return "#f59e0b"
        return "#22c55e"

    @staticmethod
    def _format_rate(bytes_per_sec: float) -> str:
        kb = 1024.0
        mb = kb * 1024.0
        gb = mb * 1024.0

        if bytes_per_sec < kb:
            return f"{bytes_per_sec:.0f} B/s"
        if bytes_per_sec < mb:
            return f"{bytes_per_sec / kb:.1f} KB/s"
        if bytes_per_sec < gb:
            return f"{bytes_per_sec / mb:.2f} MB/s"
        return f"{bytes_per_sec / gb:.2f} GB/s"

    @staticmethod
    def _as_bool(value, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("overlay/enabled", self.overlay_enabled)
        self.settings.setValue("overlay/position", self.overlay_window.pos())
        self.overlay_window.close()
        self.sampler.shutdown()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = MonitorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
