Name:           slashdigitize
Version:        0.1.0
Release:        1%{?dist}
Summary:        Audio and video digitization workstation

License:        GPL-3.0-or-later
URL:            https://github.com/slashmad/SlashDigitize
Source0:        slashdigitize-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  desktop-file-utils
BuildRequires:  appstream
BuildRequires:  python3-gobject
BuildRequires:  gtk4 >= 4.16
BuildRequires:  libadwaita >= 1.8
BuildRequires:  gtksourceview5

Requires:       python3-gobject
Requires:       gtk4 >= 4.16
Requires:       libadwaita >= 1.8
Requires:       gtksourceview5
Requires:       alsa-utils
Requires:       /usr/bin/ffmpeg
Requires:       /usr/bin/ffprobe
Requires:       gstreamer1
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
Requires:       gstreamer1-plugin-gtk4

%description
GTK4/libadwaita workstation combining direct arecord audio capture and
FFmpeg video capture, trimming, timelapse and optional VapourSynth workflows.

%prep
%autosetup -n slashdigitize-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files slashdigitize
install -Dpm 0644 data/se.slashmad.SlashDigitize.desktop %{buildroot}%{_datadir}/applications/se.slashmad.SlashDigitize.desktop

install -Dpm 0644 data/se.slashmad.SlashDigitize.metainfo.xml %{buildroot}%{_datadir}/metainfo/se.slashmad.SlashDigitize.metainfo.xml
install -Dpm 0644 data/se.slashmad.SlashDigitize.png %{buildroot}%{_datadir}/icons/hicolor/512x512/apps/se.slashmad.SlashDigitize.png

%check
PYTHONPATH=src %{python3} -B -m unittest discover -s tests -v
desktop-file-validate data/se.slashmad.SlashDigitize.desktop
appstreamcli validate --no-net --strict data/se.slashmad.SlashDigitize.metainfo.xml

%files -f %{pyproject_files}
%{_bindir}/slashdigitize
%{_datadir}/applications/se.slashmad.SlashDigitize.desktop

%license LICENSE
%doc README.md
%{_datadir}/metainfo/se.slashmad.SlashDigitize.metainfo.xml
%{_datadir}/icons/hicolor/512x512/apps/se.slashmad.SlashDigitize.png

%changelog
* Sat Nov 14 2026 slashmad - 0.1.0-1
- Import reviewed audio/video tools into SlashDigitize.
