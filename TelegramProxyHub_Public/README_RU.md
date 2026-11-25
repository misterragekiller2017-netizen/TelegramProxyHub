# Telegram Proxy Hub — Public Edition

Простая программа для Windows: собирает публичные MTProto и SOCKS5 прокси из нескольких открытых списков, проверяет TCP-доступность порта и оставляет в локальной базе только адреса, у которых порт отвечает.

## Запуск из исходников
Требуется Python 3.10+.

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
py main.py
```

## Сборка EXE на Windows
```powershell
pip install -r requirements.txt
pyinstaller --noconfirm --clean --onefile --windowed --name TelegramProxyHub main.py
```
Готовый файл будет в `dist\TelegramProxyHub.exe`. Можно также запустить `build_windows.bat`.

## Функции
- «Собрать прокси» загружает открытые списки, удаляет дубликаты, проверяет TCP-порт и удаляет недоступные записи.
- «Проверить ещё раз» повторно проверяет сохранённые адреса и удаляет недоступные.
- Порт отображается отдельной колонкой и включается в копируемую ссылку.
- MTProto копируется как `tg://proxy?...`; SOCKS5 — как `socks5://...`.
- CSV-экспорт находится в меню «Файл».

Локальная база: `%APPDATA%\TelegramProxyHub\proxies.sqlite3`.

## Ограничения
Используется несколько публичных community-списков, а не буквально весь интернет. Источники могут менять адреса и формат. TCP-проверка показывает только доступность порта, а не полноценную работу протокола, скорость или безопасность. Публичные прокси принадлежат третьим лицам; используйте их на свой риск.


## Сборка EXE без установки Python на твоём компьютере

В архив добавлен GitHub Actions workflow `.github/workflows/build-windows.yml`.
Он собирает Windows x64 EXE на облачном Windows runner GitHub:

1. Создай пустой репозиторий на GitHub.
2. Загрузи в него содержимое этой папки (включая скрытую папку `.github`).
3. Открой вкладку **Actions** и разреши запуск workflows, если GitHub попросит.
4. После завершения задания открой его страницу, внизу найди **Artifacts** и скачай `TelegramProxyHub-Windows-x64`.
5. Распакуй архив и запускай `TelegramProxyHub.exe`.

На своём ПК устанавливать Python не нужно. Для этого способа требуется аккаунт GitHub и интернет. Сам EXE создаётся на Windows runner GitHub, а не в этой среде.
