# Dota 2 Config Switcher

Графическое приложение на Python (PySide6) для переключения конфигов Dota 2 между разными наборами настроек.

Приложение копирует содержимое папки `<config_name>\570` в `<STEAM_PATH>\userdata\<STEAM_ID>\570`.

## Возможности

- Автоопределение пути Steam (реестр Windows + стандартный путь) и ручной выбор.
- Сканирование всех Steam-аккаунтов в `userdata` с пометкой наличия Dota 2 (`570`).
- Получение никнейма и аватарки через Steam Web API (опционально, нужен API-ключ).
- Список конфигов с размером и датой изменения.
- Применение конфига (зеркалирование в userdata), сохранение текущего, удаление, открытие папки.
- Кэш аватарок/профилей, логирование в `app.log`, настройки в `settings.json`.
- Тёмный интерфейс, длительные операции выполняются в фоне.

## Требования

- Windows 10/11
- Python 3.10+
- Установленный Steam (для работы с userdata)

## Установка и запуск (из исходников)

1. Клонируйте/распакуйте проект и перейдите в папку проекта.
2. Создайте виртуальное окружение:
   ```powershell
   python -m venv .venv
   ```
3. Активируйте venv:
   ```powershell
   .venv\Scripts\activate
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

В активированном venv:

```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --name "Dota2ConfigSwitcher" main.py
```

Готовый файл будет в папке `dist\Dota2ConfigSwitcher.exe`.

Если exe получается слишком большим, можно исключить неиспользуемые модули Qt, например:

```powershell
pyinstaller --onefile --windowed --name "Dota2ConfigSwitcher" ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtNetwork ^
  main.py
```

> Примечание: `QtNetwork` нужен только если вы не используете сетевые классы Qt, но в проекте загрузка через `requests`, поэтому исключение обычно безопасно. Проверяйте запуск после сборки.

## Настройки

- `settings.json` создаётся рядом с приложением/скриптом.
- Steam API-ключ можно получить здесь: https://steamcommunity.com/dev/apikey
- Без API-ключа приложение работает, но вместо никнейма/аватарки отображается SteamID.

## Структура проекта

- `main.py` — точка входа
- `steam.py` — поиск Steam, аккаунты, Steam Web API
- `configs.py` — операции с конфигами
- `settings.py` — загрузка/сохранение настроек
- `ui/` — интерфейс и фоновые задачи

## Примечания

- Перед применением/сохранением конфига рекомендуется закрыть Steam и Dota 2.
- Папка конфигов по умолчанию — рядом с исполняемым файлом/скриптом. Каждый конфиг — папка, содержащая подпапку `570`.
