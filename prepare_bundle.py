"""Проверка исходников и упаковка переносимых сборок GitHub Actions."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path.cwd()
DELIVERY = Path(__file__).resolve().parent
SERVER = ROOT / "server"
SOURCE_SHA256 = "12a2af89607d5f373dedc7e8886782ae534fd1c80627aa7253b3fc12c2d3a339"


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def extract():
    source = DELIVERY / "source-slice.zip"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA256, "Source SHA256 mismatch"
    with zipfile.ZipFile(source) as archive:
        for item in archive.infolist():
            path = Path(item.filename.replace("\\", "/"))
            assert not path.is_absolute() and ".." not in path.parts
            assert path.parts and path.parts[0] == "server"
        archive.extractall(ROOT)


def package(kind):
    target = ROOT / "work/ready" / kind
    target.mkdir(parents=True, exist_ok=False)
    if kind == "plugin":
        wasm = ROOT / "work/build/plugin/wasm32-wasip2/release/horizon_base.wasm"
        copy(wasm, target / "plugins/horizon-base.wasm")
        copy(SERVER / "config/pumpkin.toml", target / "config/pumpkin.toml")
        copy(SERVER / "config/horizon-base.toml", target / "plugins/data/horizon-base/horizon-base.toml")
        for name in ("LICENSE-MIT", "LICENSE-APACHE"):
            copy(SERVER / "engine/crates/pumpkin-plugin-api" / name, target / "licenses" / name)
        subprocess.run(["git", "-C", str(SERVER / "engine"), "archive", "--format=tar.gz",
                        "--output", str(target / "pumpkin-plugin-api-source.tar.gz"),
                        "HEAD", "crates/pumpkin-plugin-api"], check=True)
        readme = """Horizon Base — Rust/WASM\n\nЭто плагин для Pumpkin с WASM API 0.1, не .jar для Purpur.\nПроверенная привязка исходников: ff873cbbb8cc8fe591fb09aaf7d70b30517a57d0.\n\nСкопируйте plugins/ в папку тестового сервера Pumpkin.\nДля локального теста используйте config/pumpkin.toml как pumpkin.toml рядом с сервером.\nПодключение: Minecraft Java 26.3 или Horizon, адрес 127.0.0.1:25565.\nКоманда: /horizon status.\nЗащита блоков выключена; включается в plugins/data/horizon-base/horizon-base.toml.\nПлагин не является полной системой защиты территории.\nИгровая проверка выполняется отдельно после сборки.\n"""
        name = "horizon-base-wasm"
    else:
        source = ROOT / "outputs/server" / ("linux" if kind == "linux-x64" else "")
        for folder in ("bin", "plugins", "config", "licenses"):
            shutil.copytree(source / folder, target / folder)
        copy(source / "build-report.json", target / "build-report.json")
        copy(SERVER / "config/pumpkin.toml", target / "pumpkin.toml")
        copy(SERVER / "config/horizon-base.toml", target / "plugins/data/horizon-base/horizon-base.toml")
        if kind == "windows-x64":
            (target / "START-SERVER.cmd").write_bytes(
                b'@echo off\r\ncd /d "%~dp0"\r\n"%~dp0bin\\pumpkin.exe"\r\npause\r\n')
        else:
            launcher = target / "start-server.sh"
            launcher.write_text('#!/bin/sh\nset -eu\ncd -- "$(dirname -- "$0")"\nexec ./bin/pumpkin\n', encoding="utf-8")
            launcher.chmod(0o755)
            (target / "bin/pumpkin").chmod(0o755)
        subprocess.run(["git", "-C", str(SERVER / "engine"), "archive", "--format=tar.gz",
                        "--output", str(target / "pumpkin-source.tar.gz"), "HEAD"], check=True)
        readme = """Horizon Rust Server — локальная проверка\n\nРаспакуйте весь архив в отдельную новую папку.\nWindows: откройте START-SERVER.cmd.\nLinux: выполните ./start-server.sh.\n\nПосле запуска подключитесь из Minecraft Java 26.3 или Horizon: 127.0.0.1:25565.\nВ игре: /horizon status.\nОстановка сервера: команда stop в его консоли.\nМир создаётся в этой папке; существующие игровые миры не используются.\nЗащита блоков по умолчанию выключена. Её конфигурация:\nplugins/data/horizon-base/horizon-base.toml\n\nСервер: Pumpkin ff873cbbb8cc8fe591fb09aaf7d70b30517a57d0 на Rust.\nПлагин: horizon-base, WASM API 0.1.\nЭто первый тестовый срез, не полный перенос Purpur.\nИгровая проверка выполняется отдельно после сборки.\nИсходники включены в source-slice.zip и pumpkin-source.tar.gz.\n"""
        name = "horizon-rust-" + kind
    copy(SERVER / "upstream.lock.json", target / "upstream.lock.json")
    copy(SERVER / "THIRD-PARTY-NOTICES.md", target / "licenses/THIRD-PARTY-NOTICES.md")
    copy(DELIVERY / "source-slice.zip", target / "source-slice.zip")
    (target / "READ-ME.txt").write_text(readme, encoding="utf-8")
    sums = {str(path.relative_to(target)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(target.rglob("*")) if path.is_file()}
    (target / "SHA256.json").write_text(json.dumps(sums, indent=2), encoding="utf-8")
    destination = ROOT / "outputs/downloads"
    destination.mkdir(parents=True, exist_ok=True)
    if kind == "linux-x64":
        shutil.make_archive(str(destination / name), "gztar", root_dir=target)
    else:
        shutil.make_archive(str(destination / name), "zip", root_dir=target)
    print(f"Готовый пакет: {destination / name}")


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "extract":
        extract()
    elif action in ("plugin", "windows-x64", "linux-x64"):
        package(action)
    else:
        raise SystemExit("Неизвестное действие")
