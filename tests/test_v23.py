from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.coach import AIUnavailable, evaluate
from app.config import Settings
from app.main import create_app
from app.questions import BY_ID
from tests.test_core import raw_evaluation


class V23Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.tmp.name), groq_api_key='fake-key', stt_provider='groq')

    def tearDown(self):
        self.tmp.cleanup()

    def test_retry_saved_transcript_without_whisper_or_new_attempt(self):
        client = TestClient(create_app(self.settings))
        transcript = 'I practise English daily because I want to speak confidently at university.'
        with patch('app.main.evaluate', side_effect=AIUnavailable('Groq feedback request was rejected (HTTP 400)')):
            initial = client.post('/api/attempts', data={'question_id': 'p1-study-1', 'transcript': transcript})
        self.assertEqual(initial.status_code, 201)
        item = initial.json()
        self.assertIsNone(item['evaluation'])
        self.assertEqual(client.get('/api/stats').json()['total_attempts'], 1)
        from app.coach import validate_evaluation
        with patch('app.main.evaluate', return_value=validate_evaluation(raw_evaluation())) as evaluator, \
             patch('app.main.transcribe') as stt:
            retried = client.post(f"/api/attempts/{item['id']}/retry-feedback")
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()['transcript'], transcript)
        self.assertEqual(retried.json()['language_estimate_band'], 6.5)
        self.assertEqual(client.get('/api/stats').json()['total_attempts'], 1)
        self.assertEqual(client.get('/api/stats').json()['average_language_estimate'], 6.5)
        self.assertEqual(evaluator.call_count, 1)
        stt.assert_not_called()
        self.assertEqual(client.post('/api/attempts/nonexistent/retry-feedback').status_code, 404)
        client.close()

    def test_schema_400_retries_once_with_json_object_only(self):
        captured = []
        def handler(request):
            payload = json.loads(request.content)
            captured.append(payload['response_format']['type'])
            if payload['response_format']['type'] == 'json_schema':
                return httpx.Response(400, json={'error': {'type': 'invalid_request_error',
                  'code': 'invalid_json_schema', 'message': 'json_schema has invalid specification'}}, request=request)
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(raw_evaluation())}}]}, request=request)
        Client = httpx.Client
        def fake_client(*args, **kwargs):
            return Client(transport=httpx.MockTransport(handler), **kwargs)
        with patch('app.coach.httpx.Client', side_effect=fake_client):
            report = evaluate(BY_ID['p1-study-1'], 'I study English every day because I want better speaking skills.', self.settings)
        self.assertEqual(captured, ['json_schema', 'json_object'])
        self.assertEqual(report['language_estimate_band'], 6.5)

    def test_unauthorized_does_not_retry_and_400_diagnostic_does_not_leak_key(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(400, json={'error': {'type': 'invalid_request_error',
                 'code': 'bad_parameter', 'message': 'Parameter foo rejected near gsk_SECRET1234'}}, request=request)
        Client = httpx.Client
        def fake_client(*args, **kwargs):
            return Client(transport=httpx.MockTransport(handler), **kwargs)
        with patch('app.coach.httpx.Client', side_effect=fake_client):
            with self.assertLogs('app.coach', level='WARNING') as captured:
                with self.assertRaises(AIUnavailable) as result:
                    evaluate(BY_ID['p1-study-1'], 'I enjoy science because it helps me understand the world.', self.settings)
        self.assertIn('HTTP 400', str(result.exception))
        self.assertEqual(len(requests), 1)
        self.assertIn('bad_parameter', ' '.join(captured.output))
        self.assertNotIn('gsk_SECRET1234', ' '.join(captured.output))

    def test_static_ui_discloses_audio_upload_without_checkbox(self):
        html = (Path(__file__).parents[1] / 'web/index.html').read_text(encoding='utf-8')
        js = (Path(__file__).parents[1] / 'web/app.js').read_text(encoding='utf-8')
        self.assertNotIn('cloudAudioConsent', html + js)
        self.assertIn('this recording is sent to Groq Whisper', html)
        self.assertIn('form.set(\'allow_cloud_audio\'', js)
        self.assertIn('retryFeedback', js)


if __name__ == '__main__':
    unittest.main()
