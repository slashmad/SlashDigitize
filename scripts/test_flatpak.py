"""Round-trip a Flatpak bundle and test its Platform runtime without installing it."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    report = {"bundle": bundle.name, "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
              "installed": False, "hardware_opened": False, "checks": []}
    with tempfile.TemporaryDirectory(prefix="slashdigitize-flatpak-") as folder, \
            tempfile.TemporaryDirectory(prefix="flatpak-test-", dir=ROOT / "artifacts") as shared_folder:
        work, shared = Path(folder), Path(shared_folder)
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "APPDIR")}
        env["FLATPAK_USER_DIR"] = str(work / "user")

        def run(command, timeout=90):
            result = subprocess.run([str(x) for x in command], env=env, cwd=work,
                                    capture_output=True, text=True, timeout=timeout)
            if result.returncode:
                raise RuntimeError(f"Command failed: {command}\n{result.stdout}\n{result.stderr}")
            return result

        repo, app = work / "repo", work / "checkout"
        run(["ostree", f"--repo={repo}", "init", "--mode=archive"])
        run(["flatpak", "build-import-bundle", repo, bundle])
        ref = "app/se.slashmad.SlashDigitize/x86_64/stable"
        report["ostree_commit"] = run(["ostree", f"--repo={repo}", "rev-parse", ref]).stdout.strip()
        run(["ostree", f"--repo={repo}", "checkout", "--user-mode", ref, app])
        metadata = configparser.ConfigParser()
        metadata.read(app / "metadata")
        assert metadata["Application"]["runtime"] == "org.gnome.Platform/x86_64/51"
        manifest = json.loads((app / "files/manifest.json").read_text())
        permissions = manifest["finish-args"]
        assert "--talk-name=org.freedesktop.Flatpak" in permissions
        forbidden = {"AGENTS.md", "AI_CONTEXT.md", "project-memory", "claude-prototype", "codex-prototype", ".git"}
        assert not any(forbidden.intersection(p.relative_to(app / "files").parts) for p in (app / "files").rglob("*"))
        shutil.copytree(ROOT / "tests", shared / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        fixture = shared / "src/slashdigitize/host_bridge.py"
        fixture.parent.mkdir(parents=True)
        shutil.copy2(app / "files/share/slashdigitize/slashdigitize/host_bridge.py", fixture)
        options = {"PYTHONPATH": "/app/share/slashdigitize", "PYTHONDONTWRITEBYTECODE": "1",
                   "TMPDIR": str(shared), "XDG_CACHE_HOME": str(shared / "cache"),
                   "XDG_CONFIG_HOME": str(shared / "config"), "XDG_DATA_HOME": str(shared / "data"),
                   "GSK_RENDERER": "cairo", "SLASHDIGITIZE_TEST_METADATA": "1"}

        def inside(arguments, timeout=90):
            return run(["flatpak", "build", "--runtime", "--die-with-parent", *permissions,
                        *[f"--env={key}={value}" for key, value in options.items()], app,
                        "/app/bin/slashdigitize", "--python", "-B", *arguments], timeout)

        info = inside(["-c", r'''import gi,json,os,subprocess
from pathlib import Path
gi.require_version('Gtk','4.0');gi.require_version('Adw','1');gi.require_version('GtkSource','5');gi.require_version('Gst','1.0')
from gi.repository import Gtk,Adw,GtkSource,Gst,Gdk
import slashdigitize
from slashdigitize.process import is_flatpak
assert str(slashdigitize.__file__).startswith('/app/share/slashdigitize/')
assert is_flatpak()
Gst.init(None)
for name in ('gtk4paintablesink','playbin','level','v4l2src','alsasrc','audioconvert','videoconvert','decodebin'):
 assert Gst.ElementFactory.find(name),name
texture=Gdk.Texture.new_from_filename('/app/share/icons/hicolor/512x512/apps/se.slashmad.SlashDigitize.png')
assert texture.get_width()==texture.get_height()==512
versions={}
for name,arg in (('ffmpeg','-version'),('ffprobe','-version'),('arecord','--version')):
 r=subprocess.run(['flatpak-spawn','--host',name,arg],capture_output=True,text=True,check=True)
 versions[name]=(r.stdout or r.stderr).splitlines()[0]
print(json.dumps({'flatpak':True,'gtk':[Gtk.get_major_version(),Gtk.get_minor_version()],'adwaita':[Adw.get_major_version(),Adw.get_minor_version()],'host_tools':versions}))
'''])
        report["runtime_probe"] = json.loads(info.stdout.strip().splitlines()[-1])
        report["checks"].append("bundle round-trip, Platform51 GI/GTK/Adw/GtkSource/GStreamer, 512px icon, real host FFmpeg/ffprobe/arecord discovery")
        clip = shared / "synthetic.mp4"
        inside(["-c", '''import subprocess,sys,json
subprocess.run(['flatpak-spawn','--host','ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=320x240:rate=25','-frames:v','3','-c:v','libx264','-pix_fmt','yuv420p',sys.argv[1]],check=True)
r=subprocess.run(['flatpak-spawn','--host','ffprobe','-v','error','-show_streams','-of','json',sys.argv[1]],capture_output=True,text=True,check=True)
assert json.loads(r.stdout)['streams'][0]['codec_name']=='h264'
''', clip])
        inside(["-c", '''import gi,sys
gi.require_version('Gst','1.0')
from gi.repository import Gst
Gst.init(None);p=Gst.parse_launch('filesrc location="'+sys.argv[1]+'" ! decodebin ! videoconvert ! fakesink')
p.set_state(Gst.State.PLAYING);m=p.get_bus().timed_pop_filtered(15*Gst.SECOND,Gst.MessageType.EOS|Gst.MessageType.ERROR);p.set_state(Gst.State.NULL)
assert m and m.type==Gst.MessageType.EOS,m.parse_error() if m else 'timeout'
''', clip])
        report["checks"].append("host H264 encode/probe through Flatpak boundary and in-runtime GStreamer decode")
        inside(["-c", '''import os,subprocess,sys
from pathlib import Path
from slashdigitize.video.encode import write_concat_file
path=write_concat_file([sys.argv[1]],25)
assert Path(path).parent==Path(os.environ['TMPDIR'])
assert not path.startswith('/tmp/'),path
try:
 subprocess.run(['flatpak-spawn','--host','ffmpeg','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',path,'-frames:v','3','-f','null','-'],check=True)
finally:os.unlink(path)
''', clip])
        report["checks"].append("production launcher relocates default temp files; host FFmpeg reads app-created concat list from shared cache")
        runtime = work / "display"
        runtime.mkdir(mode=0o700)
        env.update(XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY="slashdigitize-flatpak-test")
        options.update(WAYLAND_DISPLAY="slashdigitize-flatpak-test", GDK_BACKEND="wayland")
        if args.screenshot:
            options["SLASHDIGITIZE_SCREENSHOT"] = str(shared / "preview.png")
        with (work / "weston.log").open("w+") as log:
            compositor = subprocess.Popen(["weston", "--backend=headless", "--width=1440", "--height=1000",
                                           "--socket=slashdigitize-flatpak-test", "--idle-time=0"],
                                          env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 10
                while not (runtime / "slashdigitize-flatpak-test").exists():
                    if compositor.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Private Weston failed to start")
                    time.sleep(.03)
                tests = inside(["-m", "unittest", "discover", "-s", shared / "tests", "-v"])
                assert "Ran 58 tests" in tests.stderr and "skipped=" not in tests.stderr, tests.stderr
                report["checks"].append("all58 tests on actual Platform51 runtime/private Weston")
                ui = inside([shared / "tests/ui_driver.py"])
                print(ui.stdout, flush=True)
                report["checks"].append("eight workflows/76 wheel guards, real host bridge with simulated recorder, capture exclusion, protected Close/Quit, async Stop and finalized shared-path WAV")
                if args.screenshot:
                    args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(shared / "preview.png", args.screenshot)
            finally:
                compositor.terminate()
                try:
                    compositor.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    compositor.kill()
                    compositor.wait()
        report["passed"] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print("PASS: exact Flatpak bundle, no application installation or capture devices.")


if __name__ == "__main__":
    main()
