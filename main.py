# Copyright (C) 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import platform
import uuid

import google.auth.transport.grpc
import google.auth.transport.requests
import google.oauth2.credentials
from google.assistant.embedded.v1alpha2 import embedded_assistant_pb2, embedded_assistant_pb2_grpc

import logger
from languages import LANG_CODE
from lib.STT import BaseSTT

NAME = 'google-assistant-stt'
API = 665

ASSISTANT_API_ENDPOINT = 'embeddedassistant.googleapis.com'
GA_CONFIG = 'google_assistant_stt_config'
GA_CREDENTIALS = 'google_assistant_credentials'
DEFAULT_GRPC_DEADLINE = 60 * 3 + 5


class Main:
    def __init__(self, cfg, log, owner):
        self.cfg = cfg
        self.log = log

        self.disable = True
        self._assistant = None

        if self._ga_init() and owner.add_stt_provider('google-assistant-stt', self.stt_wrapper):
            self.disable = False

    def start(self):
        pass

    def _ga_init(self):
        data = self._read_ga_data()
        if data is None:
            return False

        model_id, project_id, credentials = data
        data = self._get_device_config(model_id, project_id, credentials)
        if data is None:
            return False

        id_, model_id, = data

        grpc_channel = self._create_grpc_channel(credentials)
        if grpc_channel is None:
            return False
        self._assistant = STTAssistant(
            language_code=LANG_CODE.get('IETF'),
            channel=grpc_channel,
            device_model_id=model_id,
            device_id=id_,
            deadline_sec=DEFAULT_GRPC_DEADLINE,

        )
        return True

    def _create_grpc_channel(self, credentials):
        try:
            return google.auth.transport.grpc.secure_authorized_channel(
                credentials, google.auth.transport.requests.Request(), ASSISTANT_API_ENDPOINT)
        except Exception as e:
            self.log('Error creating grpc channel: {}'.format(e), logger.CRIT)
            return None

    def _read_ga_data(self):
        credentials = self.cfg.load_dict(GA_CREDENTIALS)
        if not isinstance(credentials, dict):
            self.log('Error loading credentials from \'{}\''.format(GA_CREDENTIALS), logger.CRIT)
            return None
        data = {
            'model_id': credentials.pop('model_id_stt', None) or credentials.pop('model_id', None),
            'project_id': credentials.pop('project_id', None)
        }
        for key, val in data.items():
            if not isinstance(val, str) or not val:
                self.log('Wrong or missing \'{}\' in {}. Add this key.'.format(key, GA_CREDENTIALS), logger.CRIT)
                return None
        try:
            credentials = google.oauth2.credentials.Credentials(token=None, **credentials)
            credentials.refresh(google.auth.transport.requests.Request())
        except Exception as e:
            self.log('Error initialization credentials \'{}\': {}'.format(GA_CREDENTIALS, e), logger.CRIT)
            return None
        return data['model_id'], data['project_id'], credentials

    def _get_device_config(self, model_id: str, project_id: str, credentials):
        keys = ('id', 'model_id')

        config = self.cfg.load_dict(GA_CONFIG)
        id_ = None
        if isinstance(config, dict):
            id_ = config.get('id')
            try:
                registered = device_exists(id_, config.get('model_id'), project_id, credentials)
            except RuntimeError as e:
                self.log(e, logger.ERROR)
                registered = False

            if registered:
                try:
                    return [config[key] for key in keys]
                except KeyError as e:
                    self.log('Configuration \'{}\' corrupted: {}'.format(GA_CONFIG, e), logger.WARN)
        try:
            config = self._registry_device(id_, model_id, project_id, credentials)
        except RuntimeError as e:
            self.log(e, logger.CRIT)
            return None
        self.cfg.save_dict(GA_CONFIG, config, True)
        return [config[key] for key in keys]

    def _registry_device(self, id_, model_id: str, project_id: str, credentials) -> dict:
        device_base_url = 'https://{}/v1alpha2/projects/{}/devices'.format(ASSISTANT_API_ENDPOINT, project_id)
        payload = {
            'id': id_ or 'stt-{}-{}'.format(platform.uname().node, uuid.uuid1()),
            'model_id': model_id,
            'client_type': 'SDK_SERVICE'
        }
        try:
            session = google.auth.transport.requests.AuthorizedSession(credentials)
            r = session.post(device_base_url, data=json.dumps(payload))
        except Exception as e:
            raise RuntimeError('Failed request to registry device: {}'.format(e))
        if r.status_code != 200:
            raise RuntimeError('Failed to register device: {}'.format(r.text))
        self.log('Registry new device \'{}\'.'.format(payload['id']), logger.INFO)
        del payload['client_type']
        return payload

    def stt_wrapper(self, audio_data, *_, **__):
        return GoogleAssistantSTT(self._assistant.stt, audio_data)


class STTAssistant:
    """
    Args:
      language_code: language for the conversation.
      device_model_id: identifier of the device model.
      device_id: identifier of the registered device instance.
      channel: authorized gRPC channel for connection to the
        Google Assistant API.
      deadline_sec: gRPC deadline in seconds for Google Assistant API call.
    """

    def __init__(self, language_code, device_model_id, device_id, channel, deadline_sec):
        self.language_code = language_code
        self.device_model_id = device_model_id
        self.device_id = device_id
        self.conversation_state = None
        self.assistant = embedded_assistant_pb2_grpc.EmbeddedAssistantStub(channel)
        self.deadline = deadline_sec

    def gen_assist_requests(self, chunks):
        """Yields: AssistRequest messages to send to the API."""

        config = embedded_assistant_pb2.AssistConfig(
            audio_in_config=embedded_assistant_pb2.AudioInConfig(
                encoding='LINEAR16',
                sample_rate_hertz=16000,
            ),
            audio_out_config=embedded_assistant_pb2.AudioOutConfig(
                encoding='LINEAR16',
                sample_rate_hertz=16000,
                volume_percentage=1,
            ),
            dialog_state_in=embedded_assistant_pb2.DialogStateIn(
                # language_code=self.language_code,
                conversation_state=self.conversation_state,
                is_new_conversation=True,
            ),
            device_config=embedded_assistant_pb2.DeviceConfig(
                device_id=self.device_id,
                device_model_id=self.device_model_id,
            )
        )
        # The first AssistRequest must contain the AssistConfig
        # and no audio data.
        yield embedded_assistant_pb2.AssistRequest(config=config)
        for data in chunks():
            # Subsequent requests need audio data, but not config.
            if data:
                yield embedded_assistant_pb2.AssistRequest(audio_in=data)

    def stt(self, chunks):
        text = ''
        for resp in self.assistant.Assist(self.gen_assist_requests(chunks), self.deadline):
            if resp.speech_results:
                text = ''.join(r.transcript for r in resp.speech_results)
            if resp.event_type == embedded_assistant_pb2.AssistResponse.END_OF_UTTERANCE and text:
                break
            if resp.dialog_state_out.conversation_state:
                self.conversation_state = resp.dialog_state_out.conversation_state
        return text


class GoogleAssistantSTT(BaseSTT):
    def __init__(self, assist, audio_data):
        ext = 'pcm'
        rate = 16000
        width = 2
        self._assist = assist
        super().__init__(None, audio_data, ext, convert_rate=rate, convert_width=width)

    def _send(self, proxy_key):
        try:
            self._text = self._assist(self._chunks)
        except Exception as e:
            raise RuntimeError(e)

    def _reply_check(self):
        pass


def device_exists(id_: str, model_id: str, project_id: str, credentials) -> bool:
    if not (id_ and model_id):
        return False
    device_url = 'https://{}/v1alpha2/projects/{}/devices/{}'.format(ASSISTANT_API_ENDPOINT, project_id, id_)
    try:
        session = google.auth.transport.requests.AuthorizedSession(credentials)
        r = session.get(device_url)
    except Exception as e:
        raise RuntimeError('Failed request to check exists device: {}'.format(e))
    if r.status_code != 200:
        return False
    try:
        model_id_r = r.json()['modelId']
    except (TypeError, KeyError):
        return False
    return model_id == model_id_r
