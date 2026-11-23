"""Local Windows notifications and a receipt shared by the dashboard and job."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree as ET

APP_ID = "ThetaHound.HoundDog"
STATUS_FILENAME = "notification-status.json"

# The sender registration is per Windows user. The message is XML generated
# by Python and passed on stdin, never interpolated into PowerShell code.
POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
    $request = ConvertFrom-Json -InputObject ([Console]::In.ReadToEnd())
    $appId = $env:HOUNDDOG_TOAST_APP_ID
    $sender = "HKCU:\Software\Classes\AppUserModelId\$appId"
    if (!(Test-Path -LiteralPath $sender)) {
        if (!$request.xml) {
            @{ state = 'setup' } | ConvertTo-Json -Compress
            exit 0
        }
        New-Item -Path $sender -Force | Out-Null
        Set-ItemProperty -LiteralPath $sender -Name DisplayName -Value 'HoundDog'
    }
    $manager = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
    $notifier = $manager::CreateToastNotifier($appId)
    # Windows PowerShell's property adapter can return null for this WinRT enum.
    $setting = ''
    try {
        $property = $notifier.GetType().GetProperty('Setting')
        $setting = [string]$property.GetValue($notifier, $null)
    } catch {
        # A test send can still verify delivery when settings are unavailable.
    }
    if (($setting -and $setting -ne 'Enabled') -or !$request.xml) {
        @{ state = 'setting'; setting = $setting } | ConvertTo-Json -Compress
        exit 0
    }
    $xml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime]::new()
    $xml.LoadXml($request.xml)
    $toast = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime]::new($xml)
    $toast.Tag = $request.tag
    $toast.SuppressPopup = !$request.banner
    $notifier.Show($toast)
    $state = 'submitted'
    if ($request.verify) {
        try {
            for ($attempt = 0; $attempt -lt 6; $attempt++) {
                if (@($manager::History.GetHistory($appId) | Where-Object { $_.Tag -eq $request.tag }).Count) {
                    $state = 'verified'
                    break
                }
                Start-Sleep -Milliseconds 250
            }
        } catch {
            # History may be disabled even when banners are allowed.
        }
    }
    @{ state = $state } | ConvertTo-Json -Compress
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""
ENCODED_COMMAND = base64.b64encode(POWERSHELL_SCRIPT.encode("utf-16-le")).decode("ascii")

WINDOWS_SETTINGS = {
    "Enabled": "Windows allows HoundDog notifications.",
    "DisabledForApplication": "Windows notifications are off for HoundDog.",
    "DisabledForUser": "Windows notifications are off for this user.",
    "DisabledByGroupPolicy": "Windows policy blocks notifications.",
    "DisabledByManifest": "Windows did not recognize HoundDog as a notification sender.",
}


def supported() -> bool:
    return sys.platform == "win32"


def windows_response(request: dict[str, Any]) -> tuple[str, str]:
    if not supported():
        return "unsupported", "Native notifications are available on Windows."
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", ENCODED_COMMAND],
            env={**os.environ, "HOUNDDOG_TOAST_APP_ID": APP_ID},
            input=json.dumps(request).encode("utf-8"), capture_output=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            details = result.stderr.decode("utf-8", "replace").strip()
            return "failed", f"Windows could not send or check notifications. {details[:240]}".strip()
        data = json.loads(result.stdout.decode("utf-8-sig"))
        state = data["state"]
        if state == "setting":
            setting = data["setting"]
            if not setting:
                return "unknown", "Windows did not report the sender setting. Send a test to check delivery."
            return ("ready" if setting == "Enabled" else "blocked",
                    WINDOWS_SETTINGS.get(setting, "Windows reports that notifications are blocked."))
        if state == "setup":
            return "setup", "Send a test to set up HoundDog as a Windows notification sender."
        if state == "verified":
            return "verified", "Windows Notification Center received the test."
        if state == "submitted":
            return "submitted", "Sent to Windows. If you missed the banner, check Notification Center (Win+N)."
    except subprocess.TimeoutExpired:
        return "failed", "Windows did not respond to the notification request in time."
    except (OSError, ValueError, KeyError, TypeError) as error:
        return "failed", f"Could not reach Windows notifications. {error}"
    return "failed", "Windows returned an unexpected notification response."


def delivery_status() -> dict[str, str]:
    state, message = windows_response({})
    return {"state": state, "message": message}


def last_delivery(db_path: Path) -> dict[str, str] | None:
    try:
        result = json.loads(db_path.with_name(STATUS_FILENAME).read_text(encoding="utf-8"))
        if isinstance(result, dict) and all(
            isinstance(result.get(key), str) for key in ("state", "message", "trigger", "at")
        ):
            return result
    except (OSError, ValueError):
        pass
    return None


def record_delivery(db_path: Path, trigger: str, state: str, message: str) -> dict[str, str]:
    status = {"state": state, "message": message, "trigger": trigger, "at": datetime.now(timezone.utc).isoformat()}
    destination = db_path.with_name(STATUS_FILENAME)
    temporary = destination.with_name(f"{destination.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(status), encoding="utf-8")
        temporary.replace(destination)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return status


def send(
    db_path: Path, trigger: str, title: str, lines: tuple[str, ...], *, sound: bool, banner: bool,
) -> dict[str, str]:
    root = ET.Element("toast")
    binding = ET.SubElement(ET.SubElement(root, "visual"), "binding", template="ToastGeneric")
    for text in (title, *lines):
        ET.SubElement(binding, "text").text = text
    if not sound:
        ET.SubElement(root, "audio", silent="true")
    state, message = windows_response({
        "xml": ET.tostring(root, encoding="unicode"),
        "tag": uuid4().hex[:16], "banner": banner, "verify": trigger == "test",
    })
    return record_delivery(db_path, trigger, state, message)
