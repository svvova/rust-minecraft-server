# Horizon Rust Server

Первый тестовый Rust-сервер на закреплённом Pumpkin и собственный Rust/WASM-плагин `horizon-base`. Цель — Minecraft Java 26.3 и Horizon. Это не полный перенос Purpur; Java `.jar`-плагины не используются.

Исходники находятся в `source-slice.zip` (папка `server/` внутри архива). Полный неизменённый Pumpkin загружается на commit `ff873cbbb8cc8fe591fb09aaf7d70b30517a57d0`. При распаковке сборка проверяет SHA-256 архива, затем commit, Cargo.lock и лицензии движка.

В Actions вручную запустите **Build downloadable Rust server**. Независимо собираются:

- `horizon-base-wasm`: WASM-плагин, его конфигурация и исходники;
- `horizon-rust-windows-x64`: сервер, плагин и `START-SERVER.cmd`;
- `horizon-rust-linux-x64`: сервер, плагин и `start-server.sh`.

Готовые пакеты появятся в Artifacts успешного запуска. Распакуйте Windows-пакет в новую папку и откройте `START-SERVER.cmd`. Подключитесь к `127.0.0.1:25565`, затем выполните `/horizon status` в игре. Для штатной остановки введите `stop` в консоли сервера.

Защита блоков по умолчанию выключена. Настройки: `plugins/data/horizon-base/horizon-base.toml`. Сборка не заменяет игровую проверку входа, блоков и сохранения после рестарта. Существующие миры для теста не используются.
