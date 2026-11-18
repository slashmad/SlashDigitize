"""Build a source snapshot, wheels/sdist and optionally a Fedora RPM; never install."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpm", action="store_true")
    parser.add_argument("--deb", action="store_true")
    parser.add_argument("--flatpak", action="store_true", help="Requires installed GNOME51 SDK/runtime; no downloads or installation")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = (args.out or root / "dist").resolve()
    out.mkdir(parents=True, exist_ok=True)
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    bundle = out / f"SlashDigitize-{version}-{os.uname().machine}.flatpak"
    if args.flatpak and bundle.exists():
        raise SystemExit(f"Refusing to overwrite existing Flatpak: {bundle}")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="slashdigitize-build-") as temporary:
        work = Path(temporary)
        source = work / "source"
        source.mkdir()
        for name in ["pyproject.toml", "MANIFEST.in", "LICENSE", "README.md", "SOURCE_IMPORT.json"]:
            shutil.copyfile(root / name, source / name)
        for name in ["src", "tests", "scripts", "data", "packaging", "docs"]:
            shutil.copytree(root / name, source / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "project-memory"))
        shutil.copyfile(source / "README.md", source / "src/slashdigitize/README.md")
        def run(command):
            subprocess.run(command, cwd=source, env=env, check=True)
        run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--no-cache-dir", "--wheel-dir", str(out), "."])
        run([sys.executable, "-c", "import setuptools.build_meta; setuptools.build_meta.build_sdist('dist')"])
        archive = next((source / "dist").glob("*.tar.gz"))
        shutil.copyfile(archive, out / archive.name)
        if args.rpm:
            top = work / "rpmbuild"
            rpm_tmp = work / "rpm-tmp"
            rpm_tmp.mkdir()
            (top / "SOURCES").mkdir(parents=True)
            shutil.copyfile(archive, top / "SOURCES" / archive.name)
            run(["rpmbuild", "-ba", "--define", f"_topdir {top}",
                 "--define", f"_tmppath {rpm_tmp}", str(source / "packaging/app.spec")])
            for path in [*top.glob("RPMS/*/*.rpm"), *top.glob("SRPMS/*.rpm")]:
                shutil.copyfile(path, out / path.name)
        if args.deb:
            shutil.copytree(root / "packaging/debian", source / "debian")
            os.chmod(source / "debian/rules", 0o755)
            run(["dpkg-buildpackage", "-us", "-uc", "-b"])
            for path in work.glob("*.deb"):
                shutil.copyfile(path, out / path.name)
        if args.flatpak:
            repo = work / "flatpak-repo"
            run(["flatpak-builder", "--disable-download", "--disable-rofiles-fuse",
                 "--default-branch=stable", "--collection-id=se.slashmad.SlashDigitize",
                 f"--state-dir={work / 'flatpak-state'}", f"--repo={repo}",
                 str(work / "flatpak-build"), "packaging/flatpak-manifest.yml"])
            run(["flatpak", "build-bundle",
                 "--runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo",
                 str(repo), str(bundle), "se.slashmad.SlashDigitize", "stable"])
            with bundle.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            bundle.with_suffix(".flatpak.sha256").write_text(digest + "  " + bundle.name + "\n")
            record = {"bundle": bundle.name, "sha256": digest, "bytes": bundle.stat().st_size,
                      "app_id": "se.slashmad.SlashDigitize", "branch": "stable",
                      "runtime": f"org.gnome.Platform/{os.uname().machine}/51",
                      "runtime_commit": subprocess.check_output(
                          ["flatpak", "info", "--show-commit", "org.gnome.Platform//51"],
                          env=env, text=True).strip(),
                      "media_policy": "host Python/FFmpeg/ffprobe/arecord; optional host VapourSynth",
                      "installed": False}
            (out / "flatpak-build.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"Built artifacts in {out}; nothing installed.")


if __name__ == "__main__":
    main()
