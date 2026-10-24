@echo off
rem Токен берём из файла секретов — в самом скрипте его больше нет
set TOKEN=
for /f "usebackq delims=" %%T in ("C:\Users\light\.secrets\github_pat.txt") do set TOKEN=%%T
curl -X POST "https://uploads.github.com/repos/lightphoto2006/Guhyatama/releases/410553951/assets?name=Guhyatama-delta-49-to-50.bsdiff" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/octet-stream" --data-binary @releases/Guhyatama-delta-49-to-50.bsdiff