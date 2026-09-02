#!/usr/bin/env python3
import json
import os
from pathlib import Path


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


version = required("POMODORO_VERSION")
published_at = required("POMODORO_PUBLISHED_AT")
download_url = required("POMODORO_DOWNLOAD_URL")
upstream_sha = required("POMODORO_UPSTREAM_SHA")
ipa_size_raw = os.environ.get("POMODORO_IPA_SIZE", "").strip()
ipa_size = int(ipa_size_raw) if ipa_size_raw else None
changelog = os.environ.get("POMODORO_CHANGELOG", "").strip() or f"Automated build from upstream commit {upstream_sha[:7]}."

source_path = Path("source.json")
source = json.loads(source_path.read_text(encoding="utf-8")) if source_path.exists() else {}
apps = source.get("apps") if isinstance(source.get("apps"), list) else []

bundle_id = "com.tsymlov.alexey.Pomodoro-Timer"
old_app = next((a for a in apps if isinstance(a, dict) and a.get("bundleIdentifier") == bundle_id), {})
existing_versions = old_app.get("versions") if isinstance(old_app.get("versions"), list) else []

new_version = {
    "version": version,
    "date": published_at,
    "localizedDescription": changelog,
    "downloadURL": download_url,
    "minOSVersion": "18.0"
}
if ipa_size is not None:
    new_version["size"] = ipa_size

versions = [v for v in existing_versions if str(v.get("version", "")) != version]
versions.insert(0, new_version)
versions = versions[:30]

app = {
    "name": "Pomodoro Timer",
    "bundleIdentifier": bundle_id,
    "developerName": "Alexey Tsymlov",
    "subtitle": "Minimal focus timer",
    "localizedDescription": "A clean SwiftUI Pomodoro timer with 25-minute focus sessions, short and long breaks, per-session goals, statistics, automatic cycling, local notifications and persistent settings. This IPA is an unofficial automated build of the upstream MIT-licensed project.",
    "versionDescription": changelog,
    "iconURL": "https://raw.githubusercontent.com/Tsymlov/Pomodoro-Timer/dev/Pomodoro%20Timer/Assets.xcassets/AppIcon.appiconset/AppIcon.png",
    "screenshotURLs": [],
    "versions": versions,
    "version": version,
    "versionDate": published_at,
    "downloadURL": download_url,
    "appPermissions": {}
}
if ipa_size is not None:
    app["size"] = ipa_size

other_apps = [a for a in apps if not (isinstance(a, dict) and a.get("bundleIdentifier") == bundle_id)]
source.update({
    "name": "hc6q iOS Source",
    "identifier": "dev.hc6q.pixelix-ios-source",
    "subtitle": "Automated open-source iOS builds",
    "description": "Unofficial unsigned iOS builds compiled automatically from open-source upstream projects for Feather and other AltStore-compatible source readers.",
    "iconURL": "https://github.com/hc6q.png",
    "website": "https://github.com/hc6q/pixelix",
    "apps": other_apps + [app],
    "news": source.get("news") if isinstance(source.get("news"), list) else []
})

source_path.write_text(json.dumps(source, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Updated {source_path} for Pomodoro Timer {version}; source now has {len(source['apps'])} apps.")
