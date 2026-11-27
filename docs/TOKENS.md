# Ключи и токены Guhyatama

Дата: 2026-11-27. Здесь только **где взять** и **куда класть** — значений токенов в репозитории нет и быть не должно.

## 1. Токен для скачивания книг (`githubFilesToken`)

Приложение качает приватные книги из `lightphoto2006/Guhyatama-files` через GitHub API.
Для этого в APK вшивается **read-only** fine-grained PAT (`Contents: Read-only`).

### Где взять

1. Открыть https://github.com/settings/personal-access-tokens/new
   (GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token).
2. **Resource owner**: `lightphoto2006`.
3. **Repository access** → Only select repositories:
   - `lightphoto2006/Guhyatama` — read (нужен только для проверки/скачивания релизов);
   - `lightphoto2006/Guhyatama-files` — **обязательно**, именно оттуда книги и аудио.
4. **Permissions** → Repository permissions:
   - `Contents` = **Read-only** (это единственное, что нужно приложению);
   - `Metadata` = Read-only (GitHub включает его автоматически).
   - Никаких `Administration`, `Actions`, `Secrets`, `Workflows` — не выдавать.
5. Срок действия — не больше 90 дней (GitHub сам предложит); дату записать в календарь для ротации.
6. Generate token → скопировать значение `github_pat_…` (показывается один раз).

### Куда положить

- Рабочая копия для сборки: `F:\AI\Development\Guhyatama\local.properties`

  ```properties
  githubFilesToken=github_pat_…
  ```

  `local.properties` в `.gitignore` — в git не попадает.
- Резервная копия вне репозитория (по желанию): `C:\Users\light\.secrets\github_pat_files_ro.txt`.

### Как попадает в APK

`app/build.gradle.kts` читает `githubFilesToken` из `local.properties` →
`BuildConfig.GITHUB_FILES_TOKEN` → `UpdateViewModel.downloadBook()` добавляет
`Authorization: Bearer …` для ссылок `api.github.com`.

**Важно:** токен остаётся внутри каждого уже собранного APK. После ротации старые
APK продолжают носить мёртвый токен — нужно выпускать новый APK и обновлять каталог.

### Как проверить, что токен правильный (read-only)

```powershell
$tok = ((Get-Content local.properties | Where-Object { $_ -match '^githubFilesToken=' }) -split '=',2)[1].Trim()
# 1) владелец и доступ к репозиторию книг
Invoke-RestMethod -Uri 'https://api.github.com/repos/lightphoto2006/Guhyatama-files' `
  -Headers @{ Authorization = "Bearer $tok"; 'User-Agent' = 'Guhyatama-check' }
# 2) запись должна быть запрещена (403) — значит токен read-only
#    (проверка не создаёт ничего: заведомо неверный ref)
$body = '{"ref":"refs/heads/","sha":"0000000000000000000000000000000000000000"}'
try {
  Invoke-RestMethod -Method Post -Uri 'https://api.github.com/repos/lightphoto2006/Guhyatama/git/refs' `
    -Headers @{ Authorization = "Bearer $tok"; 'User-Agent' = 'Guhyatama-check' } `
    -Body $body -ContentType 'application/json' | Out-Null
  'ОШИБКА: токен может писать — он слишком широкий'
} catch { "код $($_.Exception.Response.StatusCode.value__) (ожидается 403)" }
# 3) скачивание ассета книги (ожидается 206)
#    подставить актуальный asset id из catalog.json
```

### Когда ротировать

- При утечке/публикации APK с токеном, при смене владельца, при истечении срока.
- Плановая ротация — раз в 90 дней или чаще.
- Порядок: создать новый токен → проверить (см. выше) → заменить в `local.properties` →
  собрать новый release APK → опубликовать → старый токен отозвать на GitHub.

## 2. Токен для публикации релизов (только у владельца)

Публикация релизов (`tools/dbcomposer/gh_release.py`) берёт токен из
`git credential fill` — это GCM OAuth-токен из Credential Manager, у него есть `repo`.
Он **не** вшивается в приложение и хранится только в системном хранилище Windows.

Резервный вариант — admin fine-grained PAT из `C:\Users\light\.secrets\github_pat.txt`
(и `github_pat_catalog.txt` для `Guhyatama`). Эти ключи нельзя класть в `local.properties`:
они попадут в APK.

## 3. Прочие ключи

| Что | Где |
|---|---|
| Filebase S3 | `C:\Users\light\.secrets\filebase.json` |
| DeepSeek (AI-импорт) | `C:\Users\light\.secrets\deepseek.key` |

Значения в репозиторий, `BuildConfig` приложения и документацию не добавлять.
