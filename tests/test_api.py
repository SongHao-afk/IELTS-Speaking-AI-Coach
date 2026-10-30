from __future__ import annotations

import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_core import audio_wave, fake_groq_request


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Settings(data_dir=Path(self.tmp.name), stt_provider='none')))

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_home_questions_and_models_not_exposed_without_key(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertIn('Make your voice', self.client.get('/').text)
        self.assertEqual(self.client.get('/static/app.js').status_code, 200)
        self.assertGreater(len(self.client.get('/api/questions?part=2').json()['questions']), 5)
        self.assertFalse(self.client.get('/api/config').json()['ai_enabled'])
        self.assertEqual(len(self.client.get('/api/mock').json()['questions']), 10)

    def test_manual_text_no_fake_band_and_history(self):
        response = self.client.post('/api/attempts', data={
            'question_id': 'p1-study-1',
            'transcript': 'I enjoy studying computer science because I like solving practical problems.',
            'duration_seconds': '15.5', 'session_id': 'session-abc',
        })
        self.assertEqual(response.status_code, 201, response.text)
        entry = response.json()
        self.assertIsNone(entry['estimated_band'])
        self.assertIsNone(entry['language_estimate_band'])
        self.assertEqual(entry['transcription_source'], 'manual')
        self.assertEqual(entry['duration_seconds'], 15.5)
        self.assertEqual(self.client.get('/api/stats').json()['total_attempts'], 1)
        self.assertEqual(len(self.client.get('/api/attempts').json()['attempts']), 1)
        self.assertEqual(self.client.get('/api/attempts/' + entry['id']).status_code, 200)
        self.assertEqual(self.client.delete('/api/attempts').json()['deleted'], 1)

    def test_recorded_wav_with_manual_transcript_no_cloud_transfer(self):
        response = self.client.post('/api/attempts', data={
            'question_id': 'p2-tech-1', 'transcript': 'A text editor helped me work faster.',
            'allow_cloud_audio': 'true'}, files={'audio': ('practice.wav', audio_wave(), 'audio/wav')})
        self.assertEqual(response.status_code, 201, response.text)
        entry = response.json()
        self.assertEqual(entry['duration_seconds'], 2.0)
        self.assertEqual(entry['metrics']['audio']['duration_seconds'], 2.0)
        self.assertFalse(entry['cloud_audio_used'])

    def test_unknown_empty_audio_or_missing_transcriber_rejected(self):
        self.assertEqual(self.client.post('/api/attempts', data={
            'question_id': 'unknown', 'transcript': 'Hello there'}).status_code, 404)
        self.assertEqual(self.client.post('/api/attempts', data={
            'question_id': 'p1-study-1', 'transcript': ''}).status_code, 422)
        self.assertEqual(self.client.post('/api/attempts', data={
            'question_id': 'p1-study-1'},
            files={'audio': ('fake.wav', b'mp3 not wav', 'audio/wav')}).status_code, 422)
        self.assertEqual(self.client.post('/api/attempts', data={
            'question_id': 'p1-study-1'},
            files={'audio': ('valid.wav', audio_wave(), 'audio/wav')}).status_code, 422)

    def test_silent_microphone_rejected(self):
        raw = io.BytesIO()
        with wave.open(raw, 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(b'\x00\x00' * 32000)
        response = self.client.post('/api/attempts', data={
            'question_id': 'p1-study-1', 'transcript': 'I tried to answer this question.'},
            files={'audio': ('empty.wav', raw.getvalue(), 'audio/wav')})
        self.assertEqual(response.status_code, 422)
        self.assertIn('silent', response.json()['detail'].lower())

    def test_groq_automatic_transcription_and_feedback(self):
        settings = Settings(data_dir=Path(self.tmp.name), stt_provider='groq', groq_api_key='gsk_fake_secret_123')
        client = TestClient(create_app(settings))
        fake = fake_groq_request()
        with patch('app.coach._groq_request', fake):
            response = client.post('/api/attempts', data={
                'question_id': 'p1-study-1', 'transcript': '', 'allow_cloud_audio': 'true'},
                files={'audio': ('sample.wav', audio_wave(), 'audio/wav')})
        self.assertEqual(response.status_code, 201, response.text)
        entry = response.json()
        self.assertTrue(entry['cloud_audio_used'])
        self.assertEqual(entry['transcription_source'], 'groq_whisper')
        self.assertEqual(entry['language_estimate_band'], 6.5)
        self.assertIsNone(entry['estimated_band'])
        self.assertIsNone(entry['evaluation']['criteria']['pronunciation']['band'])
        self.assertEqual(self.client.get('/api/stats').json()['average_language_estimate'], 6.5)
        self.assertEqual(len(self.client.get('/api/stats').json()['band_trend']), 1)
        self.assertEqual([call.args[1] for call in fake.call_args_list].count('audio/transcriptions'), 1)
        self.assertEqual([call.args[1] for call in fake.call_args_list].count('chat/completions'), 1)
        cfg = client.get('/api/config').json()
        self.assertTrue(cfg['ai_enabled'])
        self.assertTrue(cfg['cloud_stt_available'])
        self.assertNotIn('groq_api_key', cfg)
        self.assertNotIn('gsk_fake_secret_123', client.get('/api/config').text)
        client.close()

    def test_manual_transcript_never_forwards_audio_even_with_consent(self):
        settings = Settings(data_dir=Path(self.tmp.name), stt_provider='groq', groq_api_key='fake-key')
        client = TestClient(create_app(settings))
        fake = fake_groq_request()
        with patch('app.coach._groq_request', fake):
            response = client.post('/api/attempts', data={
                'question_id': 'p1-study-1',
                'transcript': 'I like studying science because I can improve things in practical life.',
                'allow_cloud_audio': 'true'},
                files={'audio': ('sample.wav', audio_wave(), 'audio/wav')})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertFalse(response.json()['cloud_audio_used'])
        self.assertNotIn('audio/transcriptions', [call.args[1] for call in fake.call_args_list])
        self.assertEqual([call.args[1] for call in fake.call_args_list].count('chat/completions'), 1)
        client.close()

    def test_empty_transcript_without_audio_consent_cannot_transcribe(self):
        settings = Settings(data_dir=Path(self.tmp.name), stt_provider='groq', groq_api_key='fake-key')
        client = TestClient(create_app(settings))
        fake = fake_groq_request()
        with patch('app.coach._groq_request', fake):
            response = client.post('/api/attempts', data={
                'question_id': 'p1-study-1', 'allow_cloud_audio': 'false'},
                files={'audio': ('sample.wav', audio_wave(), 'audio/wav')})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertNotIn('audio/transcriptions', [call.args[1] for call in fake.call_args_list])
        client.close()


if __name__ == '__main__':
    unittest.main()
