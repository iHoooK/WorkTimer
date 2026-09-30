# WorkTimer

Локальный таймер для работы и стримов: сценарии с подготовкой, работой и отдыхом, Pomodoro, задачи, история времени и оверлеи OBS. Работает в трее и управляется через браузер, без аккаунта и облака.

## Требования

- Для программы: Windows 10/11 x64 и современный браузер. Python не нужен.
- Для сборки: Windows x64, Python 3.14+, Git Bash и Inno Setup 6. Первый запуск требует интернет для установки зависимостей.

## Новая сборка

Установите Python, Git и [Inno Setup 6](https://jrsoftware.org/isdl.php). В Git Bash из корня проекта выполните:

```bash
bash scripts/build.sh
```

Команда сама создаст окружение, установит зависимости, выполнит проверки и соберёт программу. Результат:

```text
Build/
├── WorkTimer-Setup-1.0.0.exe
└── Work Timer Portable/
    ├── WorkTimer.exe
    └── _internal/
```

Если Python или Inno Setup находятся нестандартно:

```bash
WORKTIMER_PYTHON='C:/Path/To/python.exe' ISCC='C:/Path/To/ISCC.exe' bash scripts/build.sh
```

[Руководство пользователя](docs/USAGE.md).
