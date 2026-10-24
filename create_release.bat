@echo off
rem Токен берём из файла секретов — в самом скрипте его больше нет
set TOKEN=
for /f "usebackq delims=" %%T in ("C:\Users\light\.secrets\github_pat.txt") do set TOKEN=%%T
curl -s -w "\nHTTP_CODE:%{http_code}" -X POST https://api.github.com/repos/lightphoto2006/Guhyatama/releases -H "Authorization: Bearer %TOKEN%" -H "Accept: application/vnd.github+json" -H "Content-Type: application/json" -d @temp\rel.json
pause