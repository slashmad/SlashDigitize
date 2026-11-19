"""Extract and verify an AppImage on private Weston; never open capture devices."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image",type=Path)
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--screenshot",type=Path)
    args=parser.parse_args()
    image=args.image.resolve()
    with image.open("rb") as stream:
        image_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    report={"image":image.name,"image_sha256":image_digest,"hardware_opened":False,"installed":False,"checks":[]}
    with tempfile.TemporaryDirectory(prefix="slashdigitize-image-test-") as folder:
        work=Path(folder)
        env={k:v for k,v in os.environ.items() if k not in ("APPDIR","PYTHONPATH","PYTHONHOME","LD_LIBRARY_PATH")}
        env.update(XDG_CACHE_HOME=str(work/"cache"),XDG_CONFIG_HOME=str(work/"config"),
                   XDG_DATA_HOME=str(work/"data"),XDG_DATA_DIRS="/nonexistent",
                   PYTHONDONTWRITEBYTECODE="1",GSK_RENDERER="cairo")
        def run(command,timeout=60):
            result=subprocess.run([str(x) for x in command],cwd=work,env=env,text=True,
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
            if result.returncode:
                raise RuntimeError(f"Command failed: {command}\n{result.stdout}\n{result.stderr}")
            return result
        run([image,"--appimage-extract"],120)
        app=work/"squashfs-root"
        launch=app/"AppRun"
        shutil.copytree(ROOT/"tests",work/"tests",ignore=shutil.ignore_patterns("__pycache__"))
        # The transport test locates this sibling fixture by its test-root path.
        fixture=work/"src/slashdigitize/host_bridge.py"
        fixture.parent.mkdir(parents=True)
        shutil.copy2(app/"usr/share/slashdigitize/slashdigitize/host_bridge.py",fixture)
        info=run([launch,"--python","-c",r'''import os,sys,json,gi,cairo,shutil,re
from pathlib import Path
gi.require_version('Gtk','4.0');gi.require_version('Adw','1');gi.require_version('GtkSource','5');gi.require_version('Gst','1.0')
from gi.repository import Gtk,Adw,GtkSource,Gst,Gdk,GLibUnix,GioUnix
import slashdigitize
root=Path(os.environ['SLASHDIGITIZE_APPDIR'])
for module in (gi,cairo,slashdigitize,json):assert Path(module.__file__).is_relative_to(root),module.__file__
assert Path(sys.prefix).is_relative_to(root)
assert not any(k in os.environ for k in ('PYTHONHOME','PYTHONPATH'))
assert Path(shutil.which('ffmpeg')).is_relative_to(root)
Gst.init(None)
for name in ('gtk4paintablesink','playbin','level','v4l2src','alsasrc','audioconvert','videoconvert','decodebin'):
 factory=Gst.ElementFactory.find(name);assert factory,name
 assert Path(factory.get_plugin().get_filename()).is_relative_to(root),factory.get_plugin().get_filename()
texture=Gdk.Texture.new_from_filename(str(root/'se.slashmad.SlashDigitize.png'))
assert texture.get_width()==1254
svg=Gdk.Texture.new_from_filename(str(root/'usr/share/icons/Adwaita/symbolic/actions/sidebar-show-symbolic.svg'))
assert svg.get_width()>0
base=('libc.so','libm.so','libmvec.so','libdl.so','libpthread.so','librt.so','libresolv.so','libnss_','ld-linux')
external=[]
for line in Path('/proc/self/maps').read_text().splitlines():
 parts=line.split()
 if len(parts)<6:continue
 path=parts[-1]
 if path.startswith('/') and re.search(r'\.so(?:\.\d+)*$',path) and not Path(path).is_relative_to(root) and not Path(path).name.startswith(base):external.append(path)
assert not external,sorted(set(external))
print(json.dumps({'prefix':sys.prefix,'external_nonbaseline_libraries':external,'icon':texture.get_width(),'gtk':[Gtk.get_major_version(),Gtk.get_minor_version()],'adwaita':[Adw.get_major_version(),Adw.get_minor_version()]}))
'''])
        report["runtime_probe"]=json.loads(info.stdout.strip().splitlines()[-1])
        assert "CRITICAL" not in info.stderr,info.stderr
        report["checks"].append("bundled Python/GI/GTK/Adw/GtkSource/Cairo/GStreamer; PNG and sandboxed SVG loaders; no external nonbaseline library mappings")
        ffmpeg=run([launch,"--ffmpeg","-version"]).stdout.splitlines()[0]
        assert ffmpeg.startswith("ffmpeg version 9.0.2 "),ffmpeg
        report["ffmpeg"]=ffmpeg
        report["arecord"]=run([launch,"--arecord","--version"]).stdout.strip()
        clip=work/"synthetic.mp4"
        run([launch,"--ffmpeg","-hide_banner","-loglevel","error","-f","lavfi","-i",
             "testsrc2=size=320x240:rate=25","-frames:v","3","-c:v","libx264","-pix_fmt","yuv420p",clip])
        media=json.loads(run([launch,"--ffprobe","-v","error","-show_streams","-of","json",clip]).stdout)
        assert media["streams"][0]["codec_name"]=="h264"
        report["checks"].append("bundled FFmpeg/ffprobe synthetic H264 encode and metadata")
        run([launch,"--python","-c",'''import gi,sys
gi.require_version('Gst','1.0')
from gi.repository import Gst
Gst.init(None)
p=Gst.parse_launch('filesrc location="'+sys.argv[1]+'" ! decodebin ! videoconvert ! fakesink')
p.set_state(Gst.State.PLAYING)
message=p.get_bus().timed_pop_filtered(15*Gst.SECOND,Gst.MessageType.ERROR|Gst.MessageType.EOS)
p.set_state(Gst.State.NULL)
assert message and message.type==Gst.MessageType.EOS, message.parse_error() if message else 'timeout'
''',clip])
        report["checks"].append("bundled GStreamer synthetic video decode to fakesink")
        if (app/"usr/lib64/python3.15/site-packages/vapoursynth").is_dir():
            script=work/"blank.vpy"
            script.write_text("import vapoursynth as vs\nvs.core.std.BlankClip(width=320,height=240,length=3).set_output()\n")
            run([launch,"--python","-c",'''import subprocess,sys,vapoursynth as vs
clip=vs.core.std.BlankClip(width=320,height=240,length=3)
assert clip.get_frame(0).width==320
subprocess.run(['vspipe','--info',sys.argv[1],'-'],check=True)
''',script])
            report["checks"].append("bundled VapourSynth base filters/frame and vspipe script metadata")
        runtime=work/"runtime";runtime.mkdir(mode=0o700)
        env.update(XDG_RUNTIME_DIR=str(runtime),WAYLAND_DISPLAY="slashdigitize-appimage-test",GDK_BACKEND="wayland")
        log=work/"weston.log"
        with log.open('w+') as output:
            compositor=subprocess.Popen(["weston","--backend=headless","--width=1440","--height=1000",
                                         "--socket=slashdigitize-appimage-test","--idle-time=0"],env=env,stdout=output,stderr=output)
            try:
                deadline=time.monotonic()+10
                while not (runtime/"slashdigitize-appimage-test").exists():
                    if compositor.poll() is not None or time.monotonic()>deadline:
                        output.seek(0);raise RuntimeError(output.read())
                    time.sleep(.03)
                resources=run([launch,"--python","-c",'''import gi,json
gi.require_version('Gtk','4.0');gi.require_version('Adw','1')
from gi.repository import Gtk,Gdk,Gio,Pango
from slashdigitize.app import DigitizeApplication
app=DigitizeApplication();app.set_flags(Gio.ApplicationFlags.NON_UNIQUE);app.register(None)
theme=Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
assert theme.get_theme_name()=='Adwaita',theme.get_theme_name()
for name in ('sidebar-show-symbolic','folder-open-symbolic'):assert theme.has_icon(name),name
fontname=Gtk.Settings.get_default().get_property('gtk-font-name')
font=Gtk.Label().get_pango_context().load_font(Pango.FontDescription.from_string(fontname)).describe().get_family()
assert 'Mono' not in font,(fontname,font)
sans=Gtk.Label().get_pango_context().load_font(Pango.FontDescription.from_string('Sans 10')).describe().get_family()
assert 'Mono' not in sans,sans
print(json.dumps({'theme':theme.get_theme_name(),'desktop_font':fontname,'resolved_font':font,'generic_sans':sans}))
'''])
                report["gui_resources"]=json.loads(resources.stdout.strip().splitlines()[-1])
                report["checks"].append("bundled Adwaita standard icons and proportional desktop/generic Sans fonts")
                suite=run([launch,"--python","-B","-m","unittest","discover","-s",work/"tests","-v"])
                assert "Ran 58 tests" in suite.stderr and "OK" in suite.stderr,suite.stderr
                report["checks"].append("all58 tests from extracted bundle, on private Weston")
                env["SLASHDIGITIZE_TEST_METADATA"]="1"
                if args.screenshot:env["SLASHDIGITIZE_SCREENSHOT"]=str(args.screenshot.resolve())
                smoke=run([launch,"--python","-B",work/"tests/ui_driver.py"],75)
                print(smoke.stdout,flush=True)
                report["checks"].append("eight workflows, actual bundled FFmpeg detection,76 wheel guards, simulated capture, shared ownership, Close/Quit, async stop and finalized WAV")
            finally:
                compositor.terminate()
                try:compositor.wait(timeout=3)
                except subprocess.TimeoutExpired:compositor.kill();compositor.wait()
    report["passed"]=True
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+"\n")
    print("PASS: AppImage bundle verification; no capture devices or installation.",flush=True)


if __name__=="__main__":main()
