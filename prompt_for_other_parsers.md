# Промпт для добавления автоматизации в другие парсеры

## Промпт для AI-ассистента:

```
Мне нужно добавить автоматизацию в мой GitHub Actions workflow для парсера [НАЗВАНИЕ_ПАРСЕРА].

После запуска парсера нужно:
1. Закоммитить и запушить в репозиторий новый спарсенный CSV файл (или другой выходной файл)
2. Если файл не изменился, коммит не создавать
3. В сообщении коммита указать дату и время обновления

Файл парсера: [ПУТЬ_К_ФАЙЛУ_ПАРСЕРА]
Выходной файл: [ПУТЬ_К_CSV_ИЛИ_ДРУГОМУ_ФАЙЛУ]

Добавь в workflow шаги для:
- Настройки Git (user.email и user.name)
- Коммита и пуша выходного файла с проверкой на изменения
- Используй тот же паттерн, что в avito-parser.yml
```

## Пример использования:

```
Мне нужно добавить автоматизацию в мой GitHub Actions workflow для парсера недвижимости.

После запуска парсера нужно:
1. Закоммитить и запушить в репозиторий новый спарсенный CSV файл
2. Если файл не изменился, коммит не создавать
3. В сообщении коммита указать дату и время обновления

Файл парсера: real_estate_parser.py
Выходной файл: output/real_estate.csv

Добавь в workflow шаги для:
- Настройки Git (user.email и user.name)
- Коммита и пуша выходного файла с проверкой на изменения
- Используй тот же паттерн, что в avito-parser.yml
```

## Шаблон кода для добавления в workflow:

```yaml
      - name: Configure Git
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"

      - name: Commit and push output file
        run: |
          git add [ПУТЬ_К_ВЫХОДНОМУ_ФАЙЛУ]
          if git diff --staged --quiet; then
            echo "No changes to commit"
          else
            git commit -m "Update [ИМЯ_ФАЙЛА] - $(date +'%Y-%m-%d %H:%M:%S UTC')"
            git push
          fi
```

## Важные моменты:

1. **Проверьте checkout action** - должен быть с `persist-credentials: true`:
   ```yaml
   - uses: actions/checkout@v4
     with:
       token: ${{ secrets.GITHUB_TOKEN }}
       persist-credentials: true
   ```

2. **Права доступа** - убедитесь, что в настройках репозитория (Settings → Actions → General → Workflow permissions) разрешена запись для GitHub Actions

3. **Путь к файлу** - укажите правильный путь относительно корня репозитория

4. **Имя файла в коммите** - замените `[ИМЯ_ФАЙЛА]` на актуальное имя файла для читаемости коммитов
