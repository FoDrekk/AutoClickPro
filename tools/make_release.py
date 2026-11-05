"""Build, sign and package a release.

    python tools/make_release.py --repo owner/name [--sign] [--skip-checks]

Steps: checks (ruff, mypy, pytest) -> PyInstaller build -> version and smoke
test of the EXE -> optional code signing -> portable zip -> installer when
Inno Setup is available -> SHA256SUMS -> winget manifests.

Signing is configured through the environment so no secret is ever a file in
the repository:

    AUTOCLICK_SIGN_THUMBPRINT   SHA-1 of a code-signing certificate in the
                                Windows certificate store, or
    AUTOCLICK_SIGN_PFX          path to a .pfx file (+ AUTOCLICK_SIGN_PASSWORD)
    AUTOCLICK_SIGN_TIMESTAMP    RFC 3161 server (default: DigiCert)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "AutoClickPro"
DEFAULT_TIMESTAMP = "http://timestamp.digicert.com"
WINGET_TEMPLATES = ROOT / "packaging" / "winget"
SMOKE_SECONDS = 6


class ReleaseError(Exception):
    """A release step failed; the message says what to do."""


def read_version(root: Path = ROOT) -> str:
    text = (root / "autoclick_pro" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"(\d+\.\d+\.\d+)"', text)
    if match is None:
        raise ReleaseError("Could not read __version__ from autoclick_pro/__init__.py.")
    return match.group(1)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_checksums(files: Sequence[Path], out: Path) -> dict[str, str]:
    """Write ``sha256sum``-compatible lines and return name -> hash."""
    sums = {file.name: sha256_file(file) for file in files}
    out.write_text("".join(f"{h}  {n}\n" for n, h in sorted(sums.items())), encoding="utf-8", newline="\n")
    return sums


def make_portable_zip(dist_dir: Path, out_zip: Path) -> Path:
    """Zip a one-folder build under a top-level ``AutoClickPro`` folder."""
    if not (dist_dir / f"{APP_NAME}.exe").is_file():
        raise ReleaseError(f"{dist_dir} does not contain {APP_NAME}.exe. Build first.")
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(p for p in dist_dir.rglob("*") if p.is_file()):
            archive.write(path, Path(APP_NAME) / path.relative_to(dist_dir))
    return out_zip


def find_signtool() -> str | None:
    found = shutil.which("signtool")
    if found:
        return found
    kits = (
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    )
    candidates = sorted(kits.glob("*/x64/signtool.exe"), reverse=True) if kits.is_dir() else []
    return str(candidates[0]) if candidates else None


def find_iscc() -> str | None:
    found = shutil.which("iscc")
    if found:
        return found
    for base in (
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMFILES"),
        os.environ.get("LOCALAPPDATA", "") + r"\Programs",
    ):
        if base:
            candidate = Path(base) / "Inno Setup 6" / "ISCC.exe"
            if candidate.is_file():
                return str(candidate)
    return None


def signing_configured(env: Mapping[str, str]) -> bool:
    return bool(env.get("AUTOCLICK_SIGN_THUMBPRINT") or env.get("AUTOCLICK_SIGN_PFX"))


def sign_command(signtool: str, target: Path, env: Mapping[str, str]) -> list[str]:
    command = [
        signtool, "sign", "/fd", "sha256", "/td", "sha256",
        "/tr", env.get("AUTOCLICK_SIGN_TIMESTAMP") or DEFAULT_TIMESTAMP, "/d", "AutoClick Pro",
    ]  # fmt: skip
    thumbprint = env.get("AUTOCLICK_SIGN_THUMBPRINT")
    pfx = env.get("AUTOCLICK_SIGN_PFX")
    if thumbprint:
        command += ["/sha1", thumbprint]
    elif pfx:
        if not Path(pfx).is_file():
            raise ReleaseError(f"AUTOCLICK_SIGN_PFX points to a missing file: {pfx}")
        command += ["/f", pfx]
        if env.get("AUTOCLICK_SIGN_PASSWORD"):
            command += ["/p", env["AUTOCLICK_SIGN_PASSWORD"]]
    else:
        raise ReleaseError("Set AUTOCLICK_SIGN_THUMBPRINT or AUTOCLICK_SIGN_PFX to sign.")
    return [*command, str(target)]


def printable(command: Sequence[str]) -> str:
    """Command line for the log with the signing password hidden."""
    shown = list(command)
    for index, part in enumerate(shown[:-1]):
        if part == "/p":
            shown[index + 1] = "********"
    return " ".join(shown)


def render_template(text: str, values: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ReleaseError(f"Template needs a value for {{{{{key}}}}}.")
        return values[key]

    return re.sub(r"\{\{(\w+)\}\}", replace, text)


def render_winget(
    out_dir: Path,
    *,
    version: str,
    installer_url: str,
    installer_sha256: str,
    release_date: str,
    templates: Path = WINGET_TEMPLATES,
) -> list[Path]:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", installer_sha256):
        raise ReleaseError("The installer hash is not a SHA-256 value.")
    values = {
        "version": version,
        "installer_url": installer_url,
        "installer_sha256": installer_sha256.upper(),
        "release_date": release_date,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for template in sorted(templates.glob("*.yaml.in")):
        target = out_dir / template.name.removesuffix(".in")
        target.write_text(
            render_template(template.read_text(encoding="utf-8"), values), encoding="utf-8", newline="\n"
        )
        written.append(target)
    if not written:
        raise ReleaseError(f"No winget templates found in {templates}.")
    return written


def run(command: Sequence[str], *, cwd: Path = ROOT, what: str = "") -> None:
    print(f"\n> {printable(command)}", flush=True)
    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode != 0:
        raise ReleaseError(f"{what or command[0]} failed with exit code {result.returncode}.")


def exe_product_version(exe: Path) -> str:
    from PyInstaller.utils.win32 import versioninfo

    info = versioninfo.read_version_info_from_executable(str(exe))
    for file_info in info.kids:
        if hasattr(file_info, "kids"):
            for table in file_info.kids:
                for entry in getattr(table, "kids", []):
                    if getattr(entry, "name", "") == "ProductVersion":
                        return str(entry.val).rstrip("\x00")
    raise ReleaseError(f"{exe} has no ProductVersion resource.")


def smoke_test(exe: Path, seconds: int = SMOKE_SECONDS) -> None:
    print(f"\n> smoke test: starting {exe.name} for {seconds} s", flush=True)
    process = subprocess.Popen([str(exe)], cwd=exe.parent)
    try:
        time.sleep(seconds)
        if process.poll() is not None:
            raise ReleaseError(f"{exe.name} exited early with code {process.returncode}.")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(10)


def sign(path: Path, env: Mapping[str, str]) -> None:
    signtool = find_signtool()
    if signtool is None:
        raise ReleaseError("signtool.exe not found. Install the Windows SDK or add signtool to PATH.")
    run(sign_command(signtool, path, env), what=f"Signing {path.name}")
    run([signtool, "verify", "/pa", str(path)], what=f"Verifying the signature of {path.name}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", default="", help="GitHub owner/name; used for the winget installer URL.")
    parser.add_argument(
        "--sign", action="store_true", help="Sign the EXE and installer (needs a certificate)."
    )
    parser.add_argument("--skip-checks", action="store_true", help="Skip ruff, mypy and pytest.")
    parser.add_argument("--skip-smoke", action="store_true", help="Do not launch the built EXE.")
    parser.add_argument("--out", type=Path, default=ROOT / "release", help="Output folder.")
    args = parser.parse_args(argv)

    env = dict(os.environ)
    if args.sign and not signing_configured(env):
        raise ReleaseError("--sign needs AUTOCLICK_SIGN_THUMBPRINT or AUTOCLICK_SIGN_PFX.")
    version = read_version()
    python = sys.executable
    out = args.out
    dist = ROOT / "dist" / APP_NAME
    print(f"Releasing {APP_NAME} {version}")

    if not args.skip_checks:
        run([python, "-m", "ruff", "check", "."], what="ruff")
        run([python, "-m", "mypy"], what="mypy")
        run([python, "-m", "pytest"], what="pytest")
    run([python, "-m", "PyInstaller", "--noconfirm", "--clean", f"{APP_NAME}.spec"], what="PyInstaller")

    exe = dist / f"{APP_NAME}.exe"
    built = exe_product_version(exe)
    if built != version:
        raise ReleaseError(f"The EXE reports version {built} but __version__ is {version}.")
    if not args.skip_smoke:
        smoke_test(exe)
    if args.sign:
        sign(exe, env)

    out.mkdir(parents=True, exist_ok=True)
    artifacts: list[Path] = [make_portable_zip(dist, out / f"{APP_NAME}-{version}-win64-portable.zip")]

    installer: Path | None = None
    iscc = find_iscc()
    if iscc is None:
        print("\nInno Setup 6 not found: skipping the installer (https://jrsoftware.org/isinfo.php).")
    else:
        run([iscc, "installer.iss"], what="Inno Setup")
        built_installer = ROOT / "installer" / f"{APP_NAME}-Setup-{version}.exe"
        if not built_installer.is_file():
            raise ReleaseError(f"Inno Setup did not produce {built_installer}.")
        installer = out / built_installer.name
        shutil.copy2(built_installer, installer)
        if args.sign:
            sign(installer, env)
        artifacts.append(installer)

    sums = write_checksums(artifacts, out / "SHA256SUMS.txt")
    if installer is not None and args.repo:
        url = f"https://github.com/{args.repo}/releases/download/v{version}/{installer.name}"
        files = render_winget(
            out / "winget" / version,
            version=version,
            installer_url=url,
            installer_sha256=sums[installer.name],
            release_date=date.today().isoformat(),
        )
        print(f"\nwinget manifests: {files[0].parent}")
    elif installer is not None:
        print("\nNo --repo given: skipping the winget manifests.")

    print("\nRelease files:")
    for artifact in artifacts:
        print(f"  {artifact}  {sums[artifact.name]}")
    if not args.sign:
        print("\nNote: the files are NOT code-signed, so Windows SmartScreen will warn on first run.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReleaseError as error:
        print(f"\nRelease failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
