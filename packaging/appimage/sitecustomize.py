"""Relocate the bundled interpreter; avoid Python environment leaks to host tools."""
import os
from pathlib import Path
import sys
import tempfile
import hashlib

root=Path(os.environ["SLASHDIGITIZE_APPDIR"])
sys.path.insert(0,str(root/"usr/share/slashdigitize"))
sys.executable=str(root/"usr/bin/python3")
sys._base_executable=sys.executable
for name in ("PYTHONHOME","PYTHONPATH","PYTHONNOUSERSITE"):
    os.environ.pop(name,None)
cache_id=hashlib.sha256(str(root).encode()).hexdigest()[:12]
cache=Path(os.environ.get("XDG_CACHE_HOME",str(Path.home()/".cache")))/"SlashDigitize/appimage"/cache_id
try:
    cache.mkdir(parents=True,exist_ok=True)
except OSError:
    _temporary_cache=tempfile.TemporaryDirectory(prefix="slashdigitize-cache-")
    os.environ["XDG_CACHE_HOME"]=_temporary_cache.name
    cache=Path(_temporary_cache.name)
os.environ["GST_REGISTRY_1_0"]=str(cache/"gstreamer-registry.bin")
# Glycin configurations contain installation-prefix paths. Generate a relocated
# cache copy; do not edit installed files or disable its image-loader sandbox.
glycin=cache/"glycin-loaders"
for source in (root/"usr/share/glycin-loaders").rglob("*.conf"):
    target=glycin/source.relative_to(root/"usr/share/glycin-loaders")
    target.parent.mkdir(parents=True,exist_ok=True)
    text=source.read_text().replace("Exec=/usr/libexec/glycin-loaders/",f"Exec={root}/usr/libexec/glycin-wrappers/")
    if not target.exists() or target.read_text()!=text:target.write_text(text)
os.environ["GLYCIN_DATA_DIR"]=str(cache)
pixbuf=cache/"pixbuf-loaders.cache"
text=(root/"usr/share/slashdigitize-bundle/pixbuf-loaders.cache").read_text()
text=text.replace("/usr/lib64/gdk-pixbuf-2.0/2.10.0/loaders",str(root/"usr/lib/gdk-pixbuf/loaders"))
if not pixbuf.exists() or pixbuf.read_text()!=text:pixbuf.write_text(text)
os.environ["GDK_PIXBUF_MODULE_FILE"]=str(pixbuf)
