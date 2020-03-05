# Google Assistant Service STT plugin for mdmTerminal2
Использует Google Assistant Service в качестве STT провайдера. Имя провайдера: `google-assistant-stt`

# Установка
Если [mdmt2-google-assistant](https://github.com/Aculeasis/mdmt2-google-assistant) был успешно установлен,
 достаточно клонировать реп:
```bash
cd mdmTerminal2/src/plugins
git clone https://github.com/Aculeasis/mdmt2-google-assistant-stt
```
---
### Только для armv6l (Raspberry Pi Zero W)
Перед установкой нужно собрать пакет `grpcio` из исходников, установка бинарного пакета приведет к ошибке **Illegal Instruction** [issue#235](https://github.com/googlesamples/assistant-sdk-python/issues/235):
```
mdmTerminal2/env/bin/python -m pip install --upgrade --no-binary :all: grpcio
```
---

- [Configure the Actions Console project and the Google account](https://developers.google.com/assistant/sdk/guides/service/python/embed/config-dev-project-and-account)
- [Register a new device model and download the client secrets file](https://developers.google.com/assistant/sdk/guides/service/python/embed/register-device)

```bash
mdmTerminal2/env/bin/python -m pip install --upgrade google-auth-oauthlib[tool] google-assistant-grpc
mdmTerminal2/env/bin/google-oauthlib-tool --client-secrets path/to/client_secret_<client-id>.json --scope https://www.googleapis.com/auth/assistant-sdk-prototype --save --headless
cp ~/.config/google-oauthlib-tool/credentials.json mdmTerminal2/src/data/google_assistant_credentials.json
cd mdmTerminal2/src/plugins
git clone https://github.com/Aculeasis/mdmt2-google-assistant-stt
```
Добавить в файл `mdmTerminal2/src/data/google_assistant_credentials.json` следующие новые ключи:
- **model_id**:  `Model ID` из Device registration.
- **project_id**: `Project ID` из Project Settings.

В результате файл `google_assistant_credentials.json` должен содержать валидный JSON со следующими ключами:
```json
{"refresh_token": "...", "token_uri": "...", "client_id": "...", "client_secret": "...", "scopes": ["..."], "project_id": "...", "model_id": "..."}
```

И перезапустить терминал.

## Настройка
**settings.ini**
```ini
[settings]
providerstt = google-assistant-stt

[listener]
# GAS способен распознавать речь только в режиме реального времени. В противном случае он не будет запущен.
stream_recognition = on
# Он сам определяет окончание фраз, лучше не ставить слишком низкое значение.
silent_multiplier = 0.7
```

# Особенности
- Распознавание прерывается вместе с фразой.
Может распознать обрывок фразы случайно попавшей в буфер (актуально для `chrome_mode`).
- Не стоит верить времени в `Распознано за`. Оно считается от окончания записи до получения ответа от STT,
но т.к. GAS часто отвечает **до окончания записи** там будет просто длительность записи.
- Не используйте `google-assistant-stt` при компиляции моделей.

# Ссылки
- [mdmTerminal2](https://github.com/Aculeasis/mdmTerminal2)
- [Google Assistant SDK for devices - Python](https://github.com/googlesamples/assistant-sdk-python)
