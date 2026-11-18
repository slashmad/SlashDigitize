"""Build a Fedora45/x86_64 AppImage from installed, inventoried RPM components.

No installation or downloads. Supply the official, checksum-verified type2
runtime. This trial deliberately targets its build host's Linux/glibc baseline.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LOCK = json.loads((ROOT/"packaging/appimage/runtime-lock.json").read_text())
RUNTIME_SHA256 = RUNTIME_LOCK["sha256"]
BASE_LIBS = re.compile(r"^(ld-linux.*|lib(c|m|mvec|dl|pthread|rt|resolv|nss_.*|anl|util|thread_db|BrokenLocale)\.so(?:\..*)?)$")
NAMESPACE = {"GLib", "GLibUnix", "GObject", "GModule", "Gio", "GioUnix", "cairo", "freetype2", "HarfBuzz",
             "fontconfig", "Pango", "PangoCairo", "GdkPixbuf", "Graphene", "Gdk",
             "Gsk", "Gtk", "Adw", "GtkSource", "Gly"}


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def sha(path):
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True, help="New dedicated work directory")
    parser.add_argument("--out", type=Path, default=ROOT/"artifacts/appimage")
    args = parser.parse_args()
    if os.uname().machine != "x86_64" or sys.version_info[:2] != (3, 15):
        raise SystemExit("This trial recipe requires Fedora45 x86_64 / system Python3.15")
    if sha(args.runtime) != RUNTIME_SHA256:
        raise SystemExit("AppImage runtime checksum mismatch; refusing to execute/package it")
    work, out = args.work.resolve(), args.out.resolve()
    if work.exists():
        raise SystemExit(f"Use a new work directory: {work}")
    if out == ROOT/"dist":
        raise SystemExit("Preserve the original dist backup; select another output directory")
    app = work/"SlashDigitize.AppDir"
    app.mkdir(parents=True)
    out.mkdir(parents=True, exist_ok=True)
    copied = {}
    lib_seeds = set()

    def copy_file(source, relative, *, seed=True):
        source = Path(source)
        destination = app/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if sha(destination) != sha(source):
                raise RuntimeError(f"Conflicting files at {relative}: {source}")
        else:
            shutil.copy2(source, destination, follow_symlinks=True)
        copied[str(relative)] = str(source.resolve())
        if seed and source.read_bytes()[:4] == b"\x7fELF":
            lib_seeds.add(source.resolve())

    def copy_tree(source, relative, ignore=None):
        source = Path(source)
        for item in sorted(source.rglob("*")):
            if item.is_file() and not any(part in (ignore or ()) for part in item.relative_to(source).parts):
                copy_file(item, Path(relative)/item.relative_to(source))

    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    copy_tree(ROOT/"src/slashdigitize", "usr/share/slashdigitize/slashdigitize", {"__pycache__", "README.md"})
    copy_file(ROOT/"README.md", "usr/share/slashdigitize/slashdigitize/README.md", seed=False)
    copy_file(ROOT/"LICENSE", "usr/share/licenses/SlashDigitize/LICENSE", seed=False)
    copy_file(sys.executable, "usr/libexec/python3.15.bin")
    copy_tree(Path(sysconfig.get_path("stdlib")), f"usr/lib64/{version}",
              {"site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "ensurepip"})
    site = Path("usr/lib64")/version/"site-packages"
    for module in ("gi", "cairo", "vapoursynth"):
        spec = __import__("importlib.util", fromlist=["find_spec"]).find_spec(module)
        if spec is None:
            if module == "vapoursynth": continue
            raise RuntimeError(f"Required Python module absent: {module}")
        source = Path(spec.origin).parent
        copy_tree(source, site/module, {"__pycache__"})
        if module == "vapoursynth":
            # The library is loaded from usr/lib, then dlopens its base filters
            # beside itself; these are not discoverable through ldd alone.
            for filters in source.glob("libvapoursynthfilters*.so"):
                copy_file(filters,Path("usr/lib")/filters.name)
    for source in Path("/usr/lib64/girepository-1.0").glob("*.typelib"):
        namespace = source.name.rsplit("-", 1)[0]
        if namespace.startswith("Gst") or namespace in NAMESPACE:
            if namespace in {"Gtk", "Gdk", "Gsk"} and "-4.0." not in source.name: continue
            if namespace == "GtkSource" and source.name != "GtkSource-5.typelib": continue
            copy_file(source, Path("usr/lib/girepository-1.0")/source.name, seed=False)
    for name in ("libgtk-4.so.1", "libadwaita-1.so.0", "libgtksourceview-5.so.0", "libgdk_pixbuf-2.0.so.0"):
        copy_file(Path("/usr/lib64")/name, Path("usr/lib")/name)
    # GStreamer discovers these through dlopen, not ELF DT_NEEDED.
    copy_tree("/usr/lib64/gstreamer-1.0", "usr/lib/gstreamer-1.0")
    copy_file("/usr/libexec/gstreamer-1.0/gst-plugin-scanner", "usr/libexec/gst-plugin-scanner.bin")
    for source in Path("/usr/lib64/gio/modules").glob("*.so"):
        if source.name in {"libgiognutls.so", "libgiolibproxy.so", "libgiognomeproxy.so", "libdconfsettings.so"}:
            copy_file(source, Path("usr/lib/gio/modules")/source.name)
    copy_tree("/usr/lib64/gtk-4.0", "usr/lib/gtk-4.0")
    copy_tree("/usr/share/alsa", "usr/share/alsa")
    copy_tree("/usr/lib64/alsa-lib", "usr/lib/alsa-lib")
    copy_tree("/usr/lib64/gdk-pixbuf-2.0/2.10.0/loaders", "usr/lib/gdk-pixbuf/loaders")
    copy_file("/usr/lib64/gdk-pixbuf-2.0/2.10.0/loaders.cache", "usr/share/slashdigitize-bundle/pixbuf-loaders.cache", seed=False)
    for folder in ("glib-2.0/schemas", "gtksourceview-5", "mime", "icons/Adwaita", "icons/AdwaitaLegacy",
                   "fonts/adwaita-sans-fonts", "fonts/adwaita-mono-fonts", "fonts/dejavu-sans-fonts", "fonts/google-noto-vf"):
        copy_tree(Path("/usr/share")/folder, Path("usr/share")/folder)
    copy_file("/usr/share/fontconfig/conf.avail/49-sansserif.conf","etc/fonts/conf.d/49-sansserif.conf",seed=False)
    copy_file("/usr/share/icons/hicolor/index.theme", "usr/share/icons/hicolor/index.theme", seed=False)
    copy_tree("/usr/share/glycin-loaders", "usr/share/glycin-loaders")
    copy_tree("/usr/libexec/glycin-loaders", "usr/libexec/glycin-loaders")

    programs = ["ffmpeg", "ffprobe", "arecord", "gst-inspect-1.0", "gst-launch-1.0", "v4l2-ctl", "lspci", "pactl", "bwrap"]
    bundled = []
    for name in programs:
        source = shutil.which(name)
        if source:
            copy_file(source, Path("usr/libexec")/(name+".bin")); bundled.append(name)
        elif name in programs[:5]:
            raise RuntimeError(f"Required executable missing: {name}")
    if (app/site/"vapoursynth").exists():
        import importlib.util
        vs=Path(importlib.util.find_spec("vapoursynth").origin).parent
        copy_file(vs/"vspipe","usr/libexec/vspipe.bin")
        copy_file(ROOT/"packaging/appimage/vspipe_launch.py", "usr/share/slashdigitize-launch/vspipe.py", seed=False)
    # Resolve transitive dependencies, flattening SONAME aliases while detecting
    # collisions. Glibc/loader and hardware-driver implementations stay host-owned.
    def dependencies(source):
        result = subprocess.run(["ldd",str(source)],capture_output=True,text=True)
        if "not found" in result.stdout:
            raise RuntimeError(f"Missing build-host dependency: {source}\n{result.stdout}")
        return [(Path(match[1]),match[0]) for match in re.findall(r"\s*(\S+) => (/\S+) \(",result.stdout)]
    scanned = set()
    while lib_seeds - scanned:
        batch = sorted(lib_seeds - scanned); scanned.update(batch)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(dependencies,batch))
        for libs in results:
            for source, soname in libs:
                if not BASE_LIBS.match(soname): copy_file(source,Path("usr/lib")/soname)
    print(f"Collected {len(copied)} files / {len(scanned)} ELF objects",flush=True)

    def write(relative,text,executable=False):
        path=app/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        if executable:path.chmod(0o755)

    for name in ["python3",*bundled,"gst-plugin-scanner"]:
        binary="python3.15" if name=="python3" else name
        before='export PYTHONHOME="$SLASHDIGITIZE_APPDIR/usr"\n' if name=="python3" else ""
        safe="-P " if name=="python3" else ""
        write(Path("usr/bin")/name, '#!/bin/sh\nset -eu\n'+before+
              f'exec /lib64/ld-linux-x86-64.so.2 --library-path "$SLASHDIGITIZE_APPDIR/usr/lib" '
              f'"$SLASHDIGITIZE_APPDIR/usr/libexec/{binary}.bin" {safe}"$@"\n',True)
    # Glycin clears its child environment and normally exposes only the helper
    # executable. Keep its sandbox, but expose this read-only payload too so the
    # helper's explicit loader can resolve bundled libraries instead of host ones.
    write("usr/bin/bwrap", '''#!/bin/sh
set -eu
for argument do
  case "$argument" in
    "$SLASHDIGITIZE_APPDIR"/usr/libexec/glycin-wrappers/*)
      exec /lib64/ld-linux-x86-64.so.2 --library-path "$SLASHDIGITIZE_APPDIR/usr/lib" "$SLASHDIGITIZE_APPDIR/usr/libexec/bwrap.bin" --ro-bind "$SLASHDIGITIZE_APPDIR" "$SLASHDIGITIZE_APPDIR" --ro-bind /bin/sh /bin/sh "$@" ;;
  esac
done
exec /lib64/ld-linux-x86-64.so.2 --library-path "$SLASHDIGITIZE_APPDIR/usr/lib" "$SLASHDIGITIZE_APPDIR/usr/libexec/bwrap.bin" "$@"
''',True)
    for loader in (app/"usr/libexec/glycin-loaders").rglob("*"):
        if loader.is_file() and loader.read_bytes()[:4]==b"\x7fELF":
            relative=loader.relative_to(app/"usr/libexec/glycin-loaders")
            write(Path("usr/libexec/glycin-wrappers")/relative,
                  '#!/bin/sh\nset -eu\nroot=${0%/usr/libexec/glycin-wrappers/*}\n'
                  f'exec /lib64/ld-linux-x86-64.so.2 --library-path "$root/usr/lib" "$root/usr/libexec/glycin-loaders/{relative}" "$@"\n',True)
    if (app/site/"vapoursynth").exists():
        write("usr/bin/vspipe",'#!/bin/sh\nexec "$SLASHDIGITIZE_APPDIR/usr/bin/python3" "$SLASHDIGITIZE_APPDIR/usr/share/slashdigitize-launch/vspipe.py" "$@"\n',True)
    copy_file(ROOT/"packaging/appimage/sitecustomize.py",site/"sitecustomize.py",seed=False)
    copy_file(ROOT/"packaging/appimage/AppRun","AppRun",seed=False)
    copy_file(ROOT/"packaging/appimage/README.md","usr/share/doc/slashdigitize/APPIMAGE.md",seed=False)
    copy_file(ROOT/"packaging/appimage/runtime-lock.json","usr/share/slashdigitize-bundle/runtime-lock.json",seed=False)
    (app/"AppRun").chmod(0o755)
    copy_file(ROOT/"data/se.slashmad.SlashDigitize.desktop","se.slashmad.SlashDigitize.desktop",seed=False)
    copy_file(ROOT/"data/se.slashmad.SlashDigitize.png","se.slashmad.SlashDigitize.png",seed=False)
    (app/".DirIcon").symlink_to("se.slashmad.SlashDigitize.png")
    write("usr/bin/slashdigitize",'#!/bin/sh\nexec "$SLASHDIGITIZE_APPDIR/usr/bin/python3" -m slashdigitize "$@"\n',True)
    write("etc/fonts/fonts.conf",'''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig><dir prefix="relative">../../usr/share/fonts</dir>
<cachedir prefix="xdg">fontconfig</cachedir>
<include ignore_missing="yes">conf.d</include>
<alias><family>sans-serif</family><prefer><family>Adwaita Sans</family></prefer></alias>
<alias><family>monospace</family><prefer><family>Adwaita Mono</family></prefer></alias>
</fontconfig>
''')
    # Installed component provenance and their supplied license texts.
    system_sources=sorted({path for path in copied.values() if path.startswith(("/usr/","/lib"))})
    result=subprocess.run(["rpm","-qf","--qf","%{NAME}|%{VERSION}-%{RELEASE}|%{ARCH}|%{LICENSE}\\n",*system_sources],capture_output=True,text=True)
    packages=sorted({line for line in result.stdout.splitlines() if line.count("|")==3})
    for item in packages:
        name=item.split("|")[0];folder=Path("/usr/share/licenses")/name
        if folder.is_dir():copy_tree(folder,Path("usr/share/licenses/components")/name)
    versions={name:run([str(shutil.which(name)),"-version"],capture_output=True).stdout.splitlines()[0]
              for name in ["ffmpeg","ffprobe"]}
    if any(not line.startswith(name+" version 9.0.2 ") for name,line in versions.items()):
        raise RuntimeError("This trial pins FFmpeg/ffprobe9.0.2; review the pin before updating")
    manifest={"format":"SlashDigitize AppImage trial1","baseline":"Fedora45 x86_64; build-host glibc required",
              "built_at_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"runtime_sha256":RUNTIME_SHA256,
              "runtime_source":RUNTIME_LOCK["asset_url"],
              "programs":bundled,"versions":versions,"rpm_components":packages,
              "external":["Linux/glibc baseline","GPU and capture drivers/permissions","Optional VapourSynth third-party filters/VSRepo metadata"],
              "generated_files":{str(f.relative_to(app)):sha(f) for f in sorted(app.rglob('*'))
                                 if f.is_file() and str(f.relative_to(app)) not in copied},
              "files":{name:{"sha256":sha(app/name),"source":source if source.startswith('/usr/') else "project-or-system"}
                       for name,source in sorted(copied.items())}}
    write("usr/share/slashdigitize-bundle/manifest.json",json.dumps(manifest,indent=2)+"\n")
    # Bundle tooling/runtime copyright is published with the official runtime.
    runtime_info=run([str(args.runtime.resolve()),"--appimage-version"],capture_output=True)
    runtime_version=(runtime_info.stdout or runtime_info.stderr).strip()
    manifest["runtime_version"]=runtime_version
    write("usr/share/slashdigitize-bundle/manifest.json",json.dumps(manifest,indent=2)+"\n")
    squash=work/"payload.squashfs"
    run(["mksquashfs",str(app),str(squash),"-noappend","-comp","zstd","-Xcompression-level","10","-all-root","-processors","4"],stdout=subprocess.DEVNULL)
    app_version=tomllib.loads((ROOT/"pyproject.toml").read_text())["project"]["version"]
    output=out/f"SlashDigitize-{app_version}-x86_64-fedora45.AppImage"
    if output.exists():raise RuntimeError(f"Refusing to overwrite existing artifact: {output}")
    with output.open('wb') as dest:
        for source in [args.runtime,squash]:
            with source.open('rb') as src:shutil.copyfileobj(src,dest)
    output.chmod(0o755)
    digest=sha(output)
    (out/(output.name+".sha256")).write_text(digest+"  "+output.name+"\n")
    (out/"bundle-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(f"Built {output} ({output.stat().st_size//1024//1024} MiB)\nSHA256 {digest}",flush=True)


if __name__=="__main__":main()
