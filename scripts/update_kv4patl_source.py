#!/usr/bin/env python3
import json
import os
from pathlib import Path


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def load_source(path: Path) -> dict:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


version = required("KV4PATL_VERSION")
published_at = required("KV4PATL_PUBLISHED_AT")
download_url = required("KV4PATL_DOWNLOAD_URL")
ipa_size = int(required("KV4PATL_IPA_SIZE"))
upstream_sha = required("KV4PATL_UPSTREAM_SHA")

repo = os.environ.get("GITHUB_REPOSITORY", "hc6q/pixelix")
repo_url = f"https://github.com/{repo}"
source_path = Path(os.environ.get("KV4PATL_SOURCE_PATH", "source.json"))
source = load_source(source_path)
apps = source.get("apps") if isinstance(source.get("apps"), list) else []

bundle_id = "com.blakeross.kv4patl"
old_app = next((a for a in apps if isinstance(a, dict) and a.get("bundleIdentifier") == bundle_id), {})
existing_versions = old_app.get("versions") if isinstance(old_app.get("versions"), list) else []

version_text = (
    f"Unofficial automated iPhone build of KV4P/ATL {version} from upstream commit "
    f"{upstream_sha[:7]}. Native SwiftUI companion for KV4P HT radios with Bluetooth LE voice, "
    "APRS/AX.25 packet messaging, KISS TNC transport, radio control and memories."
)

new_version = {
    "version": version,
    "date": published_at,
    "localizedDescription": version_text,
    "downloadURL": download_url,
    "minOSVersion": "17.0",
    "size": ipa_size,
}
versions = [v for v in existing_versions if str(v.get("version", "")) != version]
versions.insert(0, new_version)
versions = versions[:30]

app = {
    "name": "KV4P/ATL",
    "bundleIdentifier": bundle_id,
    "developerName": "WX4ATL",
    "subtitle": "ESP32 BLE ham-radio companion",
    "localizedDescription": (
        "A very niche native SwiftUI companion for KV4P HT amateur-radio hardware. It carries voice and "
        "KISS data over Bluetooth LE, supports APRS/AX.25 messaging and beacons, radio memories and control, "
        "and works with an ESP32 BLE firmware bridge. This IPA is an unofficial automated build of the upstream GPL source."
    ),
    "versionDescription": version_text,
    "iconURL": "https://raw.githubusercontent.com/WX4ATL/KV4P-ATL/main/web-flasher/assets/kv4p-radio-glyph.svg",
    "screenshotURLs": [],
    "versions": versions,
    "version": version,
    "versionDate": published_at,
    "downloadURL": download_url,
    "appPermissions": {},
    "size": ipa_size,
}

other_apps = [a for a in apps if not (isinstance(a, dict) and a.get("bundleIdentifier") == bundle_id)]
source.update({
    "name": "hc6q iOS Source",
    "identifier": "dev.hc6q.pixelix-ios-source",
    "subtitle": "Automated open-source iOS builds",
    "description": "Unofficial unsigned iOS builds compiled automatically from open-source upstream projects for Feather and other AltStore-compatible source readers.",
    "iconURL": "https://github.com/hc6q.png",
    "website": repo_url,
    "apps": other_apps + [app],
    "news": source.get("news") if isinstance(source.get("news"), list) else [],
})

source_path.write_text(json.dumps(source, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Updated {source_path} for KV4P/ATL {version}; source now has {len(source['apps'])} app(s).")
