# Dota 2 Config Switcher

Графическое приложение на Python (PySide6) для переключения конфигов Dota 2 между разными наборами настроек.

Приложение копирует содержимое папки `<config_name>\570` в `<STEAM_PATH>\userdata\<STEAM_ID>\570` (и обратно при сохранении).

## Возможности

- Автоопределение пути Steam (стандартный путь + реестр Windows) и ручной выбор папки.
- Сканирование аккаунтов в `<STEAM_PATH>\userdata\` (числовые Steam AccountID), проверка наличия папки `570` (Dota 2).
- Получение никнейма и аватарки через Steam Web API `GetPlayerSummaries` (опционально, требуется API-ключ).
- Кэш профилей и аватарок в папке `cache/` (обновление не чаще раза в сутки, настраивается).
- Список конфигов (папки с подпапкой `570`) с датой изменения и размером.
- Применение конфига (полная замена содержимого `userdata\<id>\570`), сохранение текущего, удаление, открытие папки в проводнике.
- Фоновые операции (копирование, запросы к API) с прогрессом/блокировкой UI.
- Локальные настройки в `settings.json`, лог в `app.log` (rotating).

## Требования

- Windows 10/11
- Python 3.10+
- Установленный Steam (для работы с `userdata`)
- Для никнеймов/аватарок: Steam Web API ключ (необязательно)

## Установка и запуск (из исходников)

> Рекомендуется работать строго в виртуальном окружении, чтобы не засорять глобальный Python.

1. Перейдите в папку проекта.
2. Создайте виртуальное окружение:
   ```powershell
   python -m venv .venv
   ```
3. Активируйте venv (Windows PowerShell):
   ```powershell
   .venv\Scripts\Activate.ps1
   ```
   или (cmd):
   ```bat
   .venv\Scripts\activate.bat
   ```
4. Установите зависимости:
   ```powershell
   pip install -r requirements.txt
   ```
5. Запустите приложение:
   ```powershell
   python main.py
   ```

## Сборка EXE (PyInstaller)

Сборку выполнять внутри активированного `.venv`.

### Быстрый способ (скрипт)
```powershell
.\build.ps1
```
С очисткой предыдущих артефактов:
```powershell
.\build.ps1 -Clean
```

### Вручную
```powershell
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name "Dota2ConfigSwitcher" main.py
```

Готовый файл: `dist\Dota2ConfigSwitcher.exe`.

Если exe получается слишком большим, можно исключить неиспользуемые модули Qt и пересобрать, например:
```powershell
pyinstaller --noconfirm --clean --onefile --windowed --name "Dota2ConfigSwitcher" ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtQuick ^
  main.py
```
После сборки обязательно проверьте запуск приложения.

## Настройка и использование

- **Путь к Steam**: определяется автоматически, при необходимости задаётся вручную в настройках.
- **Steam аккаунт**: выбирается в верхнем выпадающем списке (аккаунты из `userdata`).
- **Steam API-ключ**: указывается в настройках (ссылка «Получить ключ» открывает https://steamcommunity.com/dev/apikey). Без ключа приложение работает, но отображает `SteamID` и заглушку аватара.
- **Папка конфигов**: по умолчанию — рядом со скриптом/EXE. Каждый конфиг — папка, содержащая подпапку `570`.
- **Перед применением/сохранением** рекомендуется закрыть Steam и Dota 2, иначе возможны ошибки доступа к файлам.

## Структура проекта

- `main.py` — точка входа, логирование, запуск GUI
- `settings.py` — загрузка/сохранение `settings.json`, пути к кэшу/логу
- `steam.py` — поиск Steam, перечисление аккаунтов, Steam Web API и кэш профилей
- `configs.py` — список/валидация/копирование/удаление конфигов
- `ui/` — интерфейс (`main_window.py`, `settings_dialog.py`, виджеты, фоновые задачи)
- `build.ps1` — скрипт сборки EXE (PyInstaller)

## Хранение данных

- `settings.json` — настройки приложения
- `cache/` — кэш профилей и аватарок
- `app.log` — журнал работы приложения

Эти файлы/папки создаются рядом с приложением и добавлены в `.gitignore`.

