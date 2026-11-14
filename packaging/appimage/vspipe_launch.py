"""Run bundled native vspipe with its own embedded-Python configuration."""
import json
import os
from pathlib import Path
import sys

root=Path(os.environ["SLASHDIGITIZE_APPDIR"])
cache=Path(os.environ["GST_REGISTRY_1_0"]).parent
config=cache/"vsscript-config"/"vapoursynth"
config.mkdir(parents=True,exist_ok=True)
python=root/"usr/bin/python3"
library=root/"usr/lib/libpython3.15.so.1.0"
values=[str(python),str(library),str(int(python.stat().st_mtime))]
keys=set()
for folder in [root/"usr/lib",root/"usr/lib64/python3.15/site-packages/vapoursynth"]:
    for suffix in (".so",".so.0"):
        keys.add(str(folder/("libvsscript"+suffix)).replace("/lib64/","/lib/"))
text="\n".join(json.dumps(key,ensure_ascii=False)+" = "+json.dumps(values,ensure_ascii=False) for key in sorted(keys))+"\n"
path=config/"vapoursynth.toml"
if not path.exists() or path.read_text()!=text:path.write_text(text)
env={**os.environ,"PYTHONHOME":str(root/"usr"),"XDG_CONFIG_HOME":str(config.parent)}
loader="/lib64/ld-linux-x86-64.so.2"
os.execve(loader,[loader,"--library-path",str(root/"usr/lib"),str(root/"usr/libexec/vspipe.bin"),*sys.argv[1:]],env)
