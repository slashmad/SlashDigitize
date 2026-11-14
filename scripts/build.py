"""Build a source snapshot, wheels/sdist and optionally a Fedora RPM; never install."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpm", action="store_true")
    parser.add_argument("--flatpak", action="store_true", help="Requires installed GNOME51 SDK/runtime; no downloads or installation")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = (args.out or root / "dist").resolve()
    out.mkdir(parents=True, exist_ok=True)
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
        if args.flatpak:
            run(["flatpak-builder", "--disable-download", "--force-clean", f"--repo={out / 'flatpak-repo'}", str(work / "flatpak-build"), "packaging/flatpak-manifest.yml"])
    print(f"Built artifacts in {out}; nothing installed.")


if __name__ == "__main__":
    main()
