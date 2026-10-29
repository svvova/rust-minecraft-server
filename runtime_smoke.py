"""Запуск скачанного сервера с плагином в отдельном тестовом мире."""
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import tomllib
import zipfile
from prepare_bundle import SOURCE_SHA256

ROOT = Path.cwd()
OUT = ROOT / "outputs/smoke"
OUT.mkdir(parents=True, exist_ok=True)
WORK = ROOT / "work/runtime-smoke"
WORK.mkdir(parents=True, exist_ok=True)
STATUS = "Horizon Rust server | Pumpkin ff873cbbb8cc8fe591fb09aaf7d70b30517a57d0"
LOADED = "Loaded horizon-base (0.1.0)"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract_bundle():
    files = list((ROOT / "input").iterdir())
    assert len(files) == 1, files
    archive = files[0]
    target = WORK / "package"
    target.mkdir()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as source:
            for name in source.namelist():
                destination = (target / name).resolve()
                assert destination.is_relative_to(target.resolve())
            source.extractall(target)
    else:
        with tarfile.open(archive, "r:gz") as source:
            for entry in source.getmembers():
                assert entry.isfile() or entry.isdir(), entry.name
                assert (target / entry.name).resolve().is_relative_to(target.resolve())
            source.extractall(target, filter="data")
    checksums = json.loads((target / "SHA256.json").read_text())
    for name, expected in checksums.items():
        assert (target / name).resolve().is_relative_to(target.resolve())
        assert digest(target / name) == expected, name
    # Reuse the compiled engine and plugin; replace only the corrected profile
    # and the corresponding source archive. Keep the original build report.
    source_archive = ROOT / "source-slice.zip"
    assert digest(source_archive) == SOURCE_SHA256
    with zipfile.ZipFile(source_archive) as source:
        profile = source.read("server/config/pumpkin.toml")
    (target / "pumpkin.toml").write_bytes(profile)
    (target / "config/pumpkin.toml").write_bytes(profile)
    shutil.copy2(source_archive, target / "source-slice.zip")
    provenance = {"native_build_run": 40830602979,
                  "native_source_commit": "30857a277eeab55d14b09a685f4a80aa7c671475",
                  "original_package_sha256": digest(archive),
                  "source_archive_sha256": SOURCE_SHA256,
                  "correction": "GameMode enum spelling: Survival; native engine and WASM unchanged"}
    (target / "package-provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    checksums = {str(path.relative_to(target)).replace("\\", "/"): digest(path)
                 for path in sorted(target.rglob("*")) if path.is_file() and path.name != "SHA256.json"}
    (target / "SHA256.json").write_text(json.dumps(checksums, indent=2), encoding="utf-8")
    return target


def write_verified_package(package):
    directory = ROOT / "outputs/ready"
    directory.mkdir(parents=True)
    label = "windows-x64" if sys.platform == "win32" else "linux-x64"
    filename = directory / ("horizon-rust-" + label)
    archive = Path(shutil.make_archive(str(filename), "zip" if sys.platform == "win32" else "gztar",
                                      root_dir=package))
    return {"filename": archive.name, "sha256": digest(archive), "bytes": archive.stat().st_size}


def fixture(package, name):
    directory = WORK / name
    directory.mkdir()
    for folder in ("bin", "plugins"):
        shutil.copytree(package / folder, directory / folder)
    shutil.copy2(package / "pumpkin.toml", directory / "pumpkin.toml")
    return directory


def session(directory, label, expected_error=None):
    binary = directory / "bin" / ("pumpkin.exe" if sys.platform == "win32" else "pumpkin")
    binary.chmod(binary.stat().st_mode | 0o111)
    environment = dict(os.environ)
    for key in list(environment):
        if "TOKEN" in key or "SECRET" in key:
            environment.pop(key)
    environment["NO_COLOR"] = "1"
    environment["RUST_LOG"] = "info"
    process = subprocess.Popen([str(binary)], cwd=directory, env=environment,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    lines = []
    updates = queue.Queue()

    def reader():
        for line in process.stdout:
            clean = ANSI.sub("", line)
            lines.append(clean)
            print(f"[{label}] {clean}", end="", flush=True)
            updates.put(clean)
        updates.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    def wait_for(predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate("".join(lines)):
                return
            if process.poll() is not None:
                break
            try:
                updates.get(timeout=0.5)
            except queue.Empty:
                pass
        raise RuntimeError(f"{label}: expected server output missing; process={process.poll()}")

    try:
        wait_for(lambda output: "Server is now running." in output, 240)
        effective = tomllib.loads((directory / "pumpkin.toml").read_text(encoding="utf-8"))
        assert effective["default_level_name"] == "horizon-test", "Profile silently reset"
        assert effective["networking"]["java"]["address"] == "127.0.0.1:25565"
        assert effective["networking"]["java"]["online_mode"] is True
        assert effective["networking"]["java"]["encryption"] is True
        assert effective["telemetry"]["enabled"] is False
        for listener in ("bedrock", "query", "management", "lan_broadcast"):
            assert effective["networking"][listener]["enabled"] is False, listener
        assert effective["plugins"]["max_memory_mb"] == 128
        assert effective["plugins"]["allow_unsigned"] is False
        assert effective["plugins"]["overrides"]["horizon-base"]["allow_unsigned"] is True
        process.stdin.write("horizon status\n")
        process.stdin.flush()
        if expected_error is None:
            wait_for(lambda output: STATUS in output and LOADED in output, 30)
        else:
            wait_for(lambda output: expected_error(output), 30)
            # Give the console a chance to process the rejected plugin's command.
            time.sleep(2)
            assert STATUS not in "".join(lines), "Failed plugin still reported success"
            assert LOADED not in "".join(lines), "Failed plugin marked loaded"
        process.stdin.write("stop\n")
        process.stdin.flush()
        process.stdin.close()
        result = process.wait(timeout=90)
        thread.join(timeout=5)
        assert result == 0, f"{label}: server exit {result}"
        return {"case": label, "status": "passed", "exit_code": result}
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=20)
        thread.join(timeout=5)
        (OUT / f"{label}.log").write_text("".join(lines), encoding="utf-8")


def main():
    package = extract_bundle()
    results = []
    valid = fixture(package, "valid")
    results.append(session(valid, "online-start-status-stop"))
    saved = list(valid.rglob("level.dat"))
    assert saved, "No saved world metadata after shutdown"
    results.append(session(valid, "restart-status-stop"))
    assert all(path.exists() for path in saved)
    bad_config = fixture(package, "bad-config")
    (bad_config / "plugins/data/horizon-base/horizon-base.toml").write_text("enabled = [", encoding="utf-8")
    results.append(session(bad_config, "invalid-config", lambda output:
                           "invalid horizon-base TOML" in output and
                           "Failed to initialize plugin horizon-base" in output))
    bad_wasm = fixture(package, "bad-wasm")
    (bad_wasm / "plugins/horizon-base.wasm").write_bytes(b"broken wasm test fixture")
    results.append(session(bad_wasm, "broken-wasm", lambda output: any(
        "horizon-base.wasm" in line and any(word in line.lower() for word in
        ("error", "failed", "invalid", "unsupported", "unknown", "unable"))
        for line in output.splitlines())))
    report = {"platform": sys.platform, "cases": results,
              "saved_world_metadata": [str(path.relative_to(valid)) for path in saved],
              "real_clients_and_block_actions": "not-run",
              "verified_package": write_verified_package(package)}
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
