"""Check release package metadata and bind the Fedora payload to the tagged source."""
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from publish import digest, require


def git(*args):
    return subprocess.check_output(["git", *args])


def appimage(image, sha):
    lock = json.loads(git("show", f"{sha}:packaging/appimage/runtime-lock.json"))
    with image.open("rb") as stream:
        header = stream.read(4 * 1024 * 1024)
    offset = header.find(b"hsqs")
    while offset != -1 and hashlib.sha256(header[:offset]).hexdigest() != lock["sha256"]:
        offset = header.find(b"hsqs", offset + 1)
    require(offset > 0, "AppImage runtime differs from tagged runtime lock")
    bundle = "usr/share/slashdigitize/slashdigitize"
    manifest = "usr/share/slashdigitize-bundle/manifest.json"
    with TemporaryDirectory() as directory:
        root = Path(directory) / "payload"
        subprocess.run(["unsquashfs", "-no-progress", "-no-xattrs", "-d", root, "-o", str(offset), image, bundle, manifest], check=True)
        require((root / manifest).read_bytes() == (image.parent / "bundle-manifest.json").read_bytes(),
                "Embedded and supplied AppImage manifests differ")
        source = git("ls-tree", "-r", "-z", "--name-only", f"{sha}:src/slashdigitize").decode().split("\0")
        expected = {n for n in source if n and "__pycache__" not in Path(n).parts and "README.md" not in Path(n).parts}
        expected.add("README.md")
        files = {p.relative_to(root / bundle).as_posix(): p for p in (root / bundle).rglob("*") if p.is_file()}
        require(expected == files.keys(), "AppImage application file list differs from tagged source")
        for name, path in files.items():
            src = "README.md" if name == "README.md" else "src/slashdigitize/" + name
            require(path.read_bytes() == git("show", f"{sha}:{src}"), f"Wrong tagged application file: {name}")
    report = json.loads((image.parent / "validation.json").read_bytes())
    require(report.get("passed") is True and report.get("hardware_opened") is False and report.get("checks")
            and Path(report["image"]).name == image.name, "Missing successful AppImage validation report")
    checksum = digest(image)
    # The original published test report predates image_sha256. Bind that one report to its immutable image.
    if checksum == "61b3dc4afbf9e1585ba43b3f4c6a7491b33bce8b69d143e9111fac7e2a25969b":
        require(digest(image.parent / "validation.json") == "d7a05076af9d62622994a193e6492a2b6311816cc20ab57c45945c29c3b5182c"
                or report.get("image_sha256") == checksum, "Unrecognized historical report")
    else:
        require(report.get("image_sha256") == checksum, "AppImage test report is for a different image")


def validate(packages, version, run):
    for sidecar in packages.glob("*.sha256"):
        payload = sidecar.with_suffix("")
        require(sidecar.read_text().split() == [digest(payload), payload.name], f"Invalid {sidecar.name}")
    flatpak, = packages.glob("*.flatpak")
    record = json.loads((packages / "flatpak-build.json").read_bytes())
    require((record["bundle"], record["sha256"], record["bytes"], record["app_id"]) ==
            (flatpak.name, digest(flatpak), flatpak.stat().st_size, "se.slashmad.SlashDigitize"), "Flatpak identity differs")
    image, = packages.glob("*.AppImage")
    appimage(image, run["head_sha"])
    for rpm in packages.glob("*.rpm"):
        identity = subprocess.check_output(["rpm", "-qp", "--queryformat", "%{NAME}-%{VERSION}-%{RELEASE}", rpm], text=True)
        require(rpm.name.rsplit(".", 2)[0] == identity, f"Wrong RPM identity: {rpm.name}")
    deb, = packages.glob("*.deb")
    for field, value in [("Package", "slashdigitize"), ("Version", version + "-1"), ("Architecture", "all")]:
        require(subprocess.check_output(["dpkg-deb", "-f", deb, field], text=True).strip() == value, f"Wrong DEB {field}")
    wheel, = packages.glob("*.whl")
    with ZipFile(wheel) as archive:
        wheel_metadata = archive.read(f"slashdigitize-{version}.dist-info/METADATA")
    sdist, = packages.glob("*.tar.gz")
    with tarfile.open(sdist) as archive:
        source_metadata = archive.extractfile(f"slashdigitize-{version}/PKG-INFO").read()
    for data in (wheel_metadata, source_metadata):
        metadata = BytesParser().parsebytes(data)
        require((metadata["Name"].lower(), metadata["Version"]) == ("slashdigitize", version), "Wrong Python metadata")
