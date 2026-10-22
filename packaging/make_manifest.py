"""Write and sign the update manifest for a release (run in CI).

    UPDATE_SIGNING_KEY=<PEM> python packaging/make_manifest.py <out_dir> <repo> <mac.dmg> <win.exe>

Writes manifest.json and manifest.sig into out_dir. The app refuses any
manifest whose signature doesn't verify against ytd/appupdate.PUBLIC_KEY."""

import base64
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from Cryptodome.PublicKey import ECC
from Cryptodome.Signature import eddsa

ROOT = Path(__file__).resolve().parent.parent


def notes_for(version):
    text = (ROOT / "CHANGELOG.md").read_text("utf-8")
    m = re.search(rf"^## {re.escape(version)}\b.*?\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        sys.exit(f"CHANGELOG.md has no '## {version}' section")
    return m.group(1).strip()


def asset(path, repo, tag):
    data = Path(path).read_bytes()
    return {"url": f"https://github.com/{repo}/releases/download/{tag}/{Path(path).name}",
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    out, repo, dmg, exe = sys.argv[1:5]
    version = re.search(r'"(.+)"', (ROOT / "ytd" / "__init__.py").read_text()).group(1)
    tag = f"v{version}"
    manifest = {
        "version": version,
        "published": time.strftime("%Y-%m-%d"),
        "notes": notes_for(version),
        "assets": {"darwin-arm64": asset(dmg, repo, tag), "win32-x64": asset(exe, repo, tag)},
    }
    raw = json.dumps(manifest, indent=2).encode()
    key = ECC.import_key(os.environ["UPDATE_SIGNING_KEY"])
    sig = base64.b64encode(eddsa.new(key, "rfc8032").sign(raw))
    Path(out, "manifest.json").write_bytes(raw)
    Path(out, "manifest.sig").write_bytes(sig)
    print(raw.decode())


if __name__ == "__main__":
    main()
