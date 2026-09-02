"""UsagePulse desktop widget for New API and ChatGPT/Codex usage."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import keyring
import requests
from chatgpt_bridge import ChatGPTUsageBridge
from PySide6.QtCore import QObject, QPoint, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "UsagePulse"
LEGACY_APP_NAME = "NewApiMonitor"
ACCESS_TOKEN_SECRET = "new-api-access-token"
CHATGPT_USAGE_URL = "https://chatgpt.com/codex/cloud/settings/analytics#usage"
CONFIG_PATH = Path(__file__).with_name("config.json")


@dataclass
class Config:
    base_url: str = "https://ai-platform.5xgames.com"
    refresh_seconds: int = 1800
    low_balance_usd: float = 20.0
    quota_per_usd: int = 500_000
    newapi_user_id: str = ""
    open_chatgpt_usage_page: bool = True


def load_config() -> Config:
    try:
        values = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise TypeError("config must be an object")
        return Config(**{key: value for key, value in values.items() if key in Config.__dataclass_fields__})
    except (OSError, json.JSONDecodeError, TypeError):
        return Config()


def save_config(config: Config) -> None:
    CONFIG_PATH.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")


class NewApiClient:
    """Read New API metrics with a token kept in Windows Credential Manager."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"

    @property
    def base_url(self) -> str:
        return self.config.base_url.rstrip("/")

    @property
    def access_token(self) -> str | None:
        token = keyring.get_password(APP_NAME, ACCESS_TOKEN_SECRET)
        if token:
            return token

        # One-time migration from the original project name.
        token = keyring.get_password(LEGACY_APP_NAME, ACCESS_TOKEN_SECRET)
        if not token:
            return None
        keyring.set_password(APP_NAME, ACCESS_TOKEN_SECRET, token)
        try:
            keyring.delete_password(LEGACY_APP_NAME, ACCESS_TOKEN_SECRET)
        except keyring.errors.PasswordDeleteError:
            pass
        return token

    def save_access_token(self, token: str) -> None:
        keyring.set_password(APP_NAME, ACCESS_TOKEN_SECRET, token.strip())

    def _get_data(self, path: str, **kwargs: Any) -> Any:
        token = self.access_token
        if not self.config.newapi_user_id or not token:
            raise RuntimeError("Add your dashboard Access Token and user ID in New API settings.")

        response = self.session.get(
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "New-Api-User": self.config.newapi_user_id,
            },
            timeout=15,
            **kwargs,
        )
        self._raise_api_error(response)
        payload = response.json()
        return payload.get("data", payload) if isinstance(payload, dict) else payload

    @staticmethod
    def _raise_api_error(response: requests.Response) -> None:
        if response.ok:
            return
        try:
            body = response.json()
            message = body.get("message") if isinstance(body, dict) else response.text
        except ValueError:
            message = response.text
        raise RuntimeError(f"Request failed ({response.status_code}): {(message or 'Unknown error')[:160]}")

    def fetch_metrics(self) -> tuple[float, float]:
        user = self._get_data("/api/user/self")
        quota = float(user.get("quota", 0)) if isinstance(user, dict) else 0.0

        end_timestamp = int(time.time())
        usage = self._get_data(
            "/api/data/self",
            params={
                "start_timestamp": end_timestamp - 86_400,
                "end_timestamp": end_timestamp,
                "default_time": "hour",
            },
        )
        return quota / self.config.quota_per_usd, self._usage_usd(usage)

    def _usage_usd(self, data: Any) -> float:
        """Normalize totals returned by different New API versions."""
        candidates = ("total_quota", "quota", "total", "total_usage", "used_quota")
        if isinstance(data, dict):
            for key in candidates:
                if isinstance(data.get(key), (int, float)):
                    return float(data[key]) / self.config.quota_per_usd
            for key in ("data", "items", "records"):
                if isinstance(data.get(key), list):
                    return sum(self._usage_usd(item) for item in data[key])
        if isinstance(data, list):
            return sum(self._usage_usd(item) for item in data)
        return 0.0


class FetchWorker(QObject):
    done = Signal(float, float)
    failed = Signal(str)

    def __init__(self, client: NewApiClient) -> None:
        super().__init__()
        self.client = client

    @Slot()
    def run(self) -> None:
        try:
            self.done.emit(*self.client.fetch_metrics())
        except Exception as exc:
            self.failed.emit(str(exc))


class SettingsDialog(QDialog):
    def __init__(self, config: Config, credential_saved: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("UsagePulse Settings")

        layout = QFormLayout(self)
        self.url = QLineEdit(config.base_url)
        self.access_token = QLineEdit()
        self.access_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.access_token.setPlaceholderText(
            "Stored securely — paste a new token to replace it"
            if credential_saved
            else "Paste the dashboard Access Token (not an API key)"
        )
        self.user_id = QLineEdit(config.newapi_user_id)
        self.interval = QSpinBox()
        self.interval.setRange(60, 86_400)
        self.interval.setValue(config.refresh_seconds)
        self.threshold = QLineEdit(str(config.low_balance_usd))
        self.open_chatgpt_usage_page = QCheckBox("Open the fixed ChatGPT/Codex Usage page")
        self.open_chatgpt_usage_page.setChecked(config.open_chatgpt_usage_page)

        layout.addRow("Platform URL", self.url)
        layout.addRow("Dashboard Access Token", self.access_token)
        layout.addRow("New API user ID", self.user_id)
        help_text = QLabel(
            "Create the token in New API: Profile → Access Token. "
            "Leave this field blank to keep the saved token."
        )
        help_text.setWordWrap(True)
        layout.addRow("", help_text)
        layout.addRow("Refresh interval (seconds)", self.interval)
        layout.addRow("Low-balance alert (USD)", self.threshold)
        layout.addRow("ChatGPT button", self.open_chatgpt_usage_page)
        chatgpt_help = QLabel(
            "When disabled, the ChatGPT button does not navigate Chrome. The Refresh button still "
            "opens the Usage page when no ChatGPT page is detected."
        )
        chatgpt_help.setWordWrap(True)
        layout.addRow("", chatgpt_help)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)


class DashboardWidget(QWidget):
    """Always-visible summary widget; the tray is a secondary control surface."""

    def __init__(self, monitor: "MonitorApp") -> None:
        super().__init__()
        self._drag_origin: QPoint | None = None
        self.setWindowTitle("UsagePulse")
        self.setMinimumWidth(560)
        self.setStyleSheet(
            """
            QWidget {
                background: #f2f1eb;
                color: #171717;
                font-family: 'Segoe UI';
            }
            QGroupBox {
                border: 2px solid #292929;
                border-radius: 3px;
                margin-top: 12px;
                padding: 11px;
                font-weight: 700;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
                color: #171717;
                background: #f2f1eb;
            }
            QLabel#metric { font-size: 21px; font-weight: 800; color: #090909; }
            QLabel#detail { color: #343434; padding-top: 4px; }
            QLabel#status { color: #4c4c4c; padding: 4px 0; font-style: italic; }
            QPushButton {
                background: #202020;
                border: 2px solid #202020;
                border-radius: 3px;
                padding: 7px 12px;
                color: #f8f8f4;
                font-weight: 700;
            }
            QPushButton:hover { background: #f2f1eb; color: #171717; }
            QPushButton:pressed { background: #bdbdb8; color: #090909; }
            QPushButton:disabled { background: #c8c7c1; border-color: #777; color: #666; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        heading = QHBoxLayout()
        title = QLabel("UsagePulse")
        title.setObjectName("metric")
        heading.addWidget(title)
        heading.addStretch()
        self.refresh_button = QPushButton("Refresh")
        self.newapi_button = QPushButton("New API")
        self.chatgpt_button = QPushButton("ChatGPT")
        self.refresh_button.clicked.connect(monitor.manual_refresh)
        self.newapi_button.clicked.connect(monitor.open_settings)
        self.chatgpt_button.clicked.connect(monitor.open_chatgpt_usage)
        heading.addWidget(self.refresh_button)
        heading.addWidget(self.newapi_button)
        heading.addWidget(self.chatgpt_button)
        layout.addLayout(heading)

        self.status = QLabel("Waiting for New API data…")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        api_box = QGroupBox("New API")
        api_layout = QVBoxLayout(api_box)
        self.api_balance = QLabel("Balance: --")
        self.api_balance.setObjectName("metric")
        self.api_usage = QLabel("Last 24 hours: --")
        self.api_usage.setObjectName("detail")
        api_layout.addWidget(self.api_balance)
        api_layout.addWidget(self.api_usage)
        layout.addWidget(api_box)

        chat_box = QGroupBox("ChatGPT / Codex · Usage")
        chat_layout = QVBoxLayout(chat_box)
        self.chat_5h = QLabel("5-hour limit: Waiting for Chrome sync")
        self.chat_week = QLabel("Weekly limit: --")
        self.chat_reset = QLabel("Reset credits: --")
        for label in (self.chat_5h, self.chat_week, self.chat_reset):
            label.setObjectName("detail")
            label.setWordWrap(True)
            chat_layout.addWidget(label)
        layout.addWidget(chat_box)

        tip = QLabel("Open the ChatGPT Usage page to sync plan limits from Chrome.")
        tip.setObjectName("detail")
        tip.setWordWrap(True)
        layout.addWidget(tip)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event: Any) -> None:
        event.ignore()
        self.hide()


class MonitorApp(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.client = NewApiClient(self.config)
        self.last_balance: float | None = None
        self.last_usage: float | None = None
        self._fetch_thread: QThread | None = None
        self._fetch_worker: FetchWorker | None = None
        self.chatgpt_usage: dict[str, Any] = {}

        self.chatgpt_bridge = ChatGPTUsageBridge()
        self.chatgpt_bridge.start()

        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("UsagePulse: waiting for first update")
        menu = QMenu()
        menu.addAction("Show / Hide", self.toggle_dashboard)
        menu.addAction("Refresh", self.manual_refresh)
        menu.addAction("New API", self.open_settings)
        menu.addAction("Open ChatGPT Usage", self.open_chatgpt_usage)
        menu.addSeparator()
        menu.addAction("Quit", QApplication.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.toggle_dashboard()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self.tray.show()

        self.dashboard = DashboardWidget(self)
        self.dashboard.show()
        self.dashboard.adjustSize()
        available = self.dashboard.screen().availableGeometry()
        self.dashboard.move(available.center() - self.dashboard.rect().center())

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.config.refresh_seconds * 1000)
        self.chatgpt_timer = QTimer(self)
        self.chatgpt_timer.timeout.connect(self.refresh_chatgpt_usage)
        self.chatgpt_timer.start(3000)
        QApplication.instance().aboutToQuit.connect(self.chatgpt_bridge.close)
        self.refresh()

    def toggle_dashboard(self) -> None:
        self.dashboard.setVisible(not self.dashboard.isVisible())

    def open_chatgpt_usage(self, force: bool = False) -> bool:
        if not force and not self.config.open_chatgpt_usage_page:
            self.dashboard.status.setText(
                "ChatGPT/Codex Usage page opening is disabled. Refresh signals are sent to any open Usage page."
            )
            return False
        return QDesktopServices.openUrl(QUrl(CHATGPT_USAGE_URL))

    def manual_refresh(self) -> None:
        """Refresh all data and open the ChatGPT usage page if it is not open."""
        self.refresh(open_chatgpt_if_needed=True)

    def refresh(self, open_chatgpt_if_needed: bool = False) -> None:
        self.chatgpt_bridge.request_refresh(navigate_to_usage=open_chatgpt_if_needed)
        chatgpt_was_open = self.chatgpt_bridge.has_active_page()
        if open_chatgpt_if_needed and not chatgpt_was_open:
            self.open_chatgpt_usage(force=True)
        self.refresh_chatgpt_usage()
        QTimer.singleShot(4_500 if not chatgpt_was_open else 2_200, self.refresh_chatgpt_usage)
        if self._fetch_thread is not None and self._fetch_thread.isRunning():
            return
        chatgpt_status = "requesting ChatGPT/Codex Usage sync…"
        if open_chatgpt_if_needed and not chatgpt_was_open:
            chatgpt_status = "opening ChatGPT/Codex Usage to sync limits…"
        self.dashboard.status.setText(f"Refreshing New API data; {chatgpt_status}")
        self.dashboard.refresh_button.setEnabled(False)
        self._fetch_thread = QThread(self)
        self._fetch_worker = FetchWorker(self.client)
        self._fetch_worker.moveToThread(self._fetch_thread)
        self._fetch_thread.started.connect(self._fetch_worker.run)
        self._fetch_worker.done.connect(self.update_metrics)
        self._fetch_worker.failed.connect(self.update_error)
        self._fetch_worker.done.connect(self._fetch_thread.quit)
        self._fetch_worker.failed.connect(self._fetch_thread.quit)
        self._fetch_worker.done.connect(self._fetch_worker.deleteLater)
        self._fetch_worker.failed.connect(self._fetch_worker.deleteLater)
        self._fetch_thread.finished.connect(self._finish_refresh)
        self._fetch_thread.finished.connect(self._fetch_thread.deleteLater)
        self._fetch_thread.start()

    @Slot()
    def _finish_refresh(self) -> None:
        self._fetch_worker = None
        self._fetch_thread = None
        self.dashboard.refresh_button.setEnabled(True)

    @Slot(float, float)
    def update_metrics(self, balance: float, usage: float) -> None:
        self.last_balance = balance
        self.last_usage = usage
        message = f"Balance ${balance:,.2f} | 24h ${usage:,.2f}"
        self.tray.setToolTip("New API " + message + self._chatgpt_tooltip())
        self.dashboard.api_balance.setText(f"Balance: ${balance:,.2f}")
        self.dashboard.api_usage.setText(f"Last 24 hours: ${usage:,.2f}")
        self.dashboard.status.setText("New API updated.")
        if balance <= self.config.low_balance_usd:
            self.tray.showMessage(
                "New API low-balance alert",
                message,
                QSystemTrayIcon.MessageIcon.Warning,
                8000,
            )

    @Slot(str)
    def update_error(self, error: str) -> None:
        self.tray.setToolTip("New API request failed")
        self.dashboard.status.setText(
            f"New API data unavailable: {error}\nSelect New API to check the connection."
        )

    def refresh_chatgpt_usage(self) -> None:
        payload = self.chatgpt_bridge.snapshot()
        if payload == self.chatgpt_usage:
            return
        self.chatgpt_usage = payload
        self.dashboard.chat_5h.setText(
            "5-hour limit: " + (payload.get("five_hour") or "Waiting for Chrome sync")
        )
        self.dashboard.chat_week.setText("Weekly limit: " + (payload.get("weekly") or "--"))
        reset = " · ".join(
            value for value in (payload.get("reset_time"), payload.get("reset_cards")) if value
        )
        self.dashboard.chat_reset.setText("Reset credits: " + (reset or "--"))
        if self.last_balance is not None:
            self.update_metrics(self.last_balance, self.last_usage or 0.0)
        self.dashboard.status.setText("ChatGPT/Codex Usage updated.")

    def _chatgpt_tooltip(self) -> str:
        limits = [
            str(self.chatgpt_usage.get(key, ""))[:70]
            for key in ("five_hour", "weekly")
            if self.chatgpt_usage.get(key)
        ]
        return " · ChatGPT " + " / ".join(limits) if limits else ""

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, bool(self.client.access_token), self.dashboard)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            self.config = Config(
                base_url=dialog.url.text().strip(),
                refresh_seconds=dialog.interval.value(),
                low_balance_usd=float(dialog.threshold.text()),
                quota_per_usd=500_000,
                newapi_user_id=dialog.user_id.text().strip(),
                open_chatgpt_usage_page=dialog.open_chatgpt_usage_page.isChecked(),
            )
        except ValueError:
            QMessageBox.warning(self.dashboard, "Invalid settings", "Low-balance alert must be numeric.")
            return

        save_config(self.config)
        self.client = NewApiClient(self.config)
        if token := dialog.access_token.text().strip():
            self.client.save_access_token(token)
        self.timer.start(self.config.refresh_seconds * 1000)
        self.refresh()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "Unsupported", "No system tray is available on this device.")
        return 1
    try:
        monitor = MonitorApp()
    except OSError as exc:
        QMessageBox.information(
            None,
            "UsagePulse already running",
            f"UsagePulse could not start its local sync receiver: {exc}\n\n"
            "Close the existing UsagePulse instance before starting another one.",
        )
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
