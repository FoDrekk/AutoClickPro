import hashlib
import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("make_release", ROOT / "tools" / "make_release.py")
assert _spec and _spec.loader
make_release = importlib.util.module_from_spec(_spec)
sys.modules["make_release"] = make_release
_spec.loader.exec_module(make_release)

HASH = hashlib.sha256(b"installer").hexdigest()


def test_read_version_matches_package():
    from autoclick_pro import __version__

    assert make_release.read_version() == __version__


def test_read_version_requires_semver(tmp_path):
    package = tmp_path / "autoclick_pro"
    package.mkdir()
    (package / "__init__.py").write_text('__version__ = "2.1"\n', encoding="utf-8")
    with pytest.raises(make_release.ReleaseError):
        make_release.read_version(tmp_path)


def test_checksums_are_sha256sum_compatible(tmp_path):
    a, b = tmp_path / "b.zip", tmp_path / "a.exe"
    a.write_bytes(b"zip")
    b.write_bytes(b"exe")
    sums = make_release.write_checksums([a, b], tmp_path / "SHA256SUMS.txt")
    assert sums["a.exe"] == hashlib.sha256(b"exe").hexdigest()
    lines = (tmp_path / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert lines == [f"{sums['a.exe']}  a.exe", f"{sums['b.zip']}  b.zip"]


def test_portable_zip_layout(tmp_path):
    dist = tmp_path / "dist"
    (dist / "_internal" / "assets").mkdir(parents=True)
    (dist / "AutoClickPro.exe").write_bytes(b"MZ")
    (dist / "_internal" / "assets" / "icon.ico").write_bytes(b"ico")
    archive = make_release.make_portable_zip(dist, tmp_path / "out" / "app.zip")
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == [
            "AutoClickPro/AutoClickPro.exe",
            "AutoClickPro/_internal/assets/icon.ico",
        ]
        assert zf.testzip() is None


def test_portable_zip_needs_a_build(tmp_path):
    with pytest.raises(make_release.ReleaseError, match="Build first"):
        make_release.make_portable_zip(tmp_path, tmp_path / "x.zip")


def test_sign_command_with_thumbprint():
    env = {"AUTOCLICK_SIGN_THUMBPRINT": "ABCDEF", "AUTOCLICK_SIGN_TIMESTAMP": "http://ts.example"}
    command = make_release.sign_command("signtool.exe", Path("app.exe"), env)
    assert command[:2] == ["signtool.exe", "sign"]
    assert command[command.index("/sha1") + 1] == "ABCDEF"
    assert command[command.index("/tr") + 1] == "http://ts.example"
    assert command[command.index("/fd") + 1] == "sha256"
    assert command[-1] == "app.exe"


def test_sign_command_with_pfx_hides_password(tmp_path):
    pfx = tmp_path / "cert.pfx"
    pfx.write_bytes(b"x")
    env = {"AUTOCLICK_SIGN_PFX": str(pfx), "AUTOCLICK_SIGN_PASSWORD": "s3cret"}
    command = make_release.sign_command("signtool.exe", Path("app.exe"), env)
    assert command[command.index("/p") + 1] == "s3cret"
    assert command[command.index("/tr") + 1] == make_release.DEFAULT_TIMESTAMP
    shown = make_release.printable(command)
    assert "s3cret" not in shown and "********" in shown


def test_sign_command_errors(tmp_path):
    with pytest.raises(make_release.ReleaseError):
        make_release.sign_command("signtool.exe", Path("a.exe"), {})
    with pytest.raises(make_release.ReleaseError, match="missing file"):
        make_release.sign_command(
            "signtool.exe", Path("a.exe"), {"AUTOCLICK_SIGN_PFX": str(tmp_path / "no.pfx")}
        )
    assert not make_release.signing_configured({})
    assert make_release.signing_configured({"AUTOCLICK_SIGN_THUMBPRINT": "AA"})


def test_render_template_requires_every_value():
    assert make_release.render_template("v{{version}}", {"version": "1.0.0"}) == "v1.0.0"
    with pytest.raises(make_release.ReleaseError, match="installer_url"):
        make_release.render_template("{{installer_url}}", {})


def test_render_winget_fills_everything(tmp_path):
    files = make_release.render_winget(
        tmp_path,
        version="2.1.0",
        installer_url="https://github.com/me/app/releases/download/v2.1.0/AutoClickPro-Setup-2.1.0.exe",
        installer_sha256=HASH,
        release_date="2026-10-15",
    )
    assert len(files) == 3
    text = "\n".join(f.read_text(encoding="utf-8") for f in files)
    assert "{{" not in text
    assert "PackageVersion: 2.1.0" in text
    assert f"InstallerSha256: {HASH.upper()}" in text
    assert "ReleaseDate: 2026-10-15" in text


def test_render_winget_rejects_bad_hash(tmp_path):
    with pytest.raises(make_release.ReleaseError, match="SHA-256"):
        make_release.render_winget(
            tmp_path,
            version="2.1.0",
            installer_url="https://x",
            installer_sha256="nope",
            release_date="2026-10-15",
        )


@pytest.mark.skipif(shutil.which("winget") is None, reason="winget is not installed")
def test_rendered_manifests_pass_winget_validate(tmp_path):
    make_release.render_winget(
        tmp_path,
        version="2.1.0",
        installer_url="https://github.com/me/app/releases/download/v2.1.0/AutoClickPro-Setup-2.1.0.exe",
        installer_sha256=HASH,
        release_date="2026-10-15",
    )
    result = subprocess.run(
        ["winget", "validate", "--manifest", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_iss_reads_version_from_exe_and_builds_64_bit():
    text = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert "GetStringFileInfo" in text and "ProductVersion" in text
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in text
    assert "{7C4E9A1B-3F2D-4E6A-8C1D-5B0A9F2E4D6C}_is1" in (
        ROOT / "packaging" / "winget" / "AutoClickPro.AutoClickPro.installer.yaml.in"
    ).read_text(encoding="utf-8")
