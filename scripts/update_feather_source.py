#!/usr/bin/env python3
import base64
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
        except (json.JSONDecodeError, OSError, TypeError):
            pass
    return {}


version = required("PIXELIX_VERSION")
published_at = required("PIXELIX_PUBLISHED_AT")
download_url = required("PIXELIX_DOWNLOAD_URL")
ipa_size_raw = os.environ.get("PIXELIX_IPA_SIZE", "").strip()
ipa_size = int(ipa_size_raw) if ipa_size_raw else None
changelog_b64 = os.environ.get("PIXELIX_CHANGELOG_B64", "")
changelog = base64.b64decode(changelog_b64).decode("utf-8", errors="replace").strip() if changelog_b64 else ""
if not changelog:
    changelog = f"Automated iOS build of Pixelix {version}."

repo = os.environ.get("GITHUB_REPOSITORY", "hc6q/pixelix")
raw_base = f"https://raw.githubusercontent.com/{repo}/main"
repo_url = f"https://github.com/{repo}"
source_icon_url = "https://github.com/hc6q.png"
icon_url = f"{raw_base}/iosApp/iosApp/Assets.xcassets/AppIcon.appiconset/pixelix_logo_192.png"
screenshot_url = f"{raw_base}/assets/pixelix_screenshots.png"

source_path = Path(os.environ.get("PIXELIX_SOURCE_PATH", "source.json"))
source = load_source(source_path)
apps = source.get("apps") if isinstance(source.get("apps"), list) else []

bundle_id = "com.daniebeler.pfpixelix.iosApp"
old_app = next((a for a in apps if isinstance(a, dict) and a.get("bundleIdentifier") == bundle_id), {})
existing_versions = old_app.get("versions") if isinstance(old_app.get("versions"), list) else []

new_version = {
    "version": version,
    "date": published_at,
    "localizedDescription": changelog,
    "downloadURL": download_url,
    "minOSVersion": "16.2"
}
if ipa_size is not None:
    new_version["size"] = ipa_size

versions = [v for v in existing_versions if str(v.get("version", "")) != version]
versions.insert(0, new_version)
versions = versions[:30]

app = {
    "name": "Pixelix",
    "bundleIdentifier": bundle_id,
    "developerName": "Ghostbyte",
    "subtitle": "Pixelfed & Vernissage client",
    "localizedDescription": "An open-source client for Pixelfed and Vernissage, built with Compose Multiplatform for browsing, publishing photos and interacting across the federated social web. This IPA is an unofficial automated build of the upstream source code.",
    "versionDescription": changelog,
    "iconURL": icon_url,
    "screenshotURLs": [screenshot_url],
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
    "iconURL": source_icon_url,
    "website": repo_url,
    "apps": [app] + other_apps,
    "news": source.get("news") if isinstance(source.get("news"), list) else []
})

source_path.parent.mkdir(parents=True, exist_ok=True)
source_path.write_text(json.dumps(source, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Updated {source_path} for Pixelix {version}; source now has {len(source['apps'])} app(s).")
