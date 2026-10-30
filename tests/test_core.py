from __future__ import annotations

import io
import json
import math
import sqlite3

import httpx
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.audio import InvalidAudio, transcript_metrics, wav_metrics
from app.coach import (AIUnavailable, TranscriptionUnavailable, _groq_request,
                       evaluate, transcribe, validate_evaluation)
from app.config import Settings
from app.db import Database
from app.questions import BY_ID, QUESTIONS, all_questions, mock_questions


def audio_wave(seconds=2.0, rate=16000, silence_between=False) -> bytes:
    import struct
    frames = bytearray()
    for i in range(int(seconds * rate)):
        t = i / rate
        silence = silence_between and (0.7 <= t <= 1.4)
        sample = int(9000 * math.sin(2 * math.pi * 180 * t)) if not silence else 0
        frames.extend(struct.pack('<h', sample))
    dest = io.BytesIO()
    with wave.open(dest, 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(bytes(frames))
    return dest.getvalue()


def raw_evaluation():
    return {
        'criteria': {key: {'band': 6.5, 'evidence': 'Specific example',
                           'strength': 'Clear idea', 'improve': 'Add a relevant reason'}
                     for key in ('fluency_coherence', 'lexical_resource', 'grammar', 'pronunciation')},
        'strengths': ['Useful explanation'],
        'priorities': ['Add a more precise example'],
        'improved_answer': 'I prefer trains because they are convenient.',
        'practice_drill': 'Give two examples in 45 seconds.',
    }


def fake_groq_request():
    def respond(settings, path, **kwargs):
        if path == 'chat/completions':
            return {'choices': [{'message': {'content': json.dumps(raw_evaluation())}}]}
        if path == 'audio/transcriptions':
            return {'text': 'I really enjoy learning technology because it helps me solve new problems.'}
        raise AssertionError(f'Unexpected route: {path}')
    return Mock(side_effect=respond)


class QuestionTests(unittest.TestCase):
    def test_questions_have_unique_ids_and_three_parts(self):
        self.assertEqual(len(BY_ID), len(QUESTIONS))
        self.assertEqual({q.part for q in QUESTIONS}, {1, 2, 3})
        self.assertGreater(len(all_questions(1)), 10)

    def test_mock_structure_and_part_3_topic_follows_part_2(self):
        for seed in range(20):
            questions = mock_questions(seed)
            self.assertEqual([q['part'] for q in questions], [1, 1, 1, 1, 1, 2, 3, 3, 3, 3])
            self.assertTrue(all(q['topic'] == questions[5]['topic'] for q in questions[6:]))
            self.assertEqual(len({q['id'] for q in questions}), len(questions))


class AudioTests(unittest.TestCase):
    def test_audio_duration_energy_and_pause(self):
        m = wav_metrics(audio_wave(silence_between=True))
        self.assertAlmostEqual(m['duration_seconds'], 2.0)
        self.assertGreater(m['speech_ratio'], .3)
        self.assertLess(m['speech_ratio'], .8)
        self.assertEqual(m['pause_count'], 1)
        self.assertLess(m['clipping_percent'], 1)

    def test_invalid_audio_rejected(self):
        with self.assertRaises(InvalidAudio):
            wav_metrics(b'NOT A WAVE')

    def test_text_metrics_no_fake_score(self):
        result = transcript_metrics('Um I I went to school and it was fun because I met friends.', 10)
        self.assertGreater(result['estimated_wpm'], 0)
        self.assertEqual(result['filler_count'], 1)
        self.assertEqual(result['repeated_words'], 1)
        self.assertNotIn('band', result)


class CoachTests(unittest.TestCase):
    def setUp(self):
        self.raw = raw_evaluation()
        self.settings = Settings(data_dir=Path('/tmp'), groq_api_key='fake-key')

    def test_language_estimate_without_official_band_or_pronunciation(self):
        response = validate_evaluation(self.raw)
        self.assertEqual(response['language_estimate_band'], 6.5)
        self.assertIsNone(response['criteria']['pronunciation']['band'])
        self.assertIsNone(response['estimated_overall_band'])

    def test_incorrect_pronunciation_score_is_always_discarded(self):
        self.raw['criteria']['pronunciation']['band'] = 9
        self.assertIsNone(validate_evaluation(self.raw)['criteria']['pronunciation']['band'])

    def test_band_rounding_for_only_3_criteria(self):
        for key in ('fluency_coherence', 'lexical_resource', 'grammar'):
            self.raw['criteria'][key]['band'] = 6.0
        self.raw['criteria']['grammar']['band'] = 7.5
        self.assertEqual(validate_evaluation(self.raw)['language_estimate_band'], 6.5)

    def test_invalid_bands_never_accepted(self):
        self.raw['criteria']['grammar']['band'] = 15
        self.assertIsNone(validate_evaluation(self.raw)['language_estimate_band'])
        self.raw['criteria']['grammar']['band'] = 6.3
        self.assertIsNone(validate_evaluation(self.raw)['criteria']['grammar']['band'])
        self.raw['criteria']['grammar']['band'] = float('nan')
        self.assertIsNone(validate_evaluation(self.raw)['criteria']['grammar']['band'])

    def test_groq_feedback_sends_only_text_and_json_schema(self):
        fake = fake_groq_request()
        with patch('app.coach._groq_request', fake):
            assessment = evaluate(BY_ID['p1-study-1'], 'I like studying engineering because it helps me solve real problems.', self.settings)
        self.assertEqual(assessment['language_estimate_band'], 6.5)
        params = fake.call_args.kwargs['payload']
        self.assertEqual(params['model'], 'openai/gpt-oss-20b')
        self.assertEqual(params['response_format']['type'], 'json_schema')
        self.assertEqual(params['response_format']['json_schema']['strict'], True)
        self.assertNotIn('audio/transcriptions', str(fake.call_args))
        self.assertIsNone(assessment['estimated_overall_band'])

    def test_stt_consent_required_and_does_not_forward_without_it(self):
        fake = fake_groq_request()
        with patch('app.coach._groq_request', fake):
            with self.assertRaises(TranscriptionUnavailable):
                transcribe(audio_wave(), self.settings, False)
            fake.assert_not_called()
            text, source = transcribe(audio_wave(), self.settings, True)
        self.assertIn('learning technology', text)
        self.assertEqual(source, 'groq_whisper')
        kw = fake.call_args.kwargs
        self.assertEqual(kw['form_data']['model'], 'whisper-large-v3-turbo')
        self.assertEqual(kw['files']['file'][2], 'audio/wav')
        self.assertTrue(kw['files']['file'][1].startswith(b'RIFF'))

    def test_groq_rate_limit_is_sanitized(self):
        fake = fake_groq_request()
        exc = type('Dummy429', (Exception,), {'status_code': 429})('secret: gsk_abc')
        fake.side_effect = exc
        with patch('app.coach._groq_request', fake):
            with self.assertRaises(AIUnavailable) as context:
                evaluate(BY_ID['p1-study-1'], 'My studies focus on maths because I like solving real problems.', self.settings)
        self.assertIn('rate limit', str(context.exception).lower())
        self.assertNotIn('gsk_abc', str(context.exception))

    def test_real_http_payload_uses_documented_groq_endpoints(self):
        seen = []
        def handler(request):
            seen.append(request)
            self.assertEqual(request.headers['authorization'], 'Bearer fake-key')
            self.assertTrue(str(request.url).startswith('https://api.groq.com/openai/v1/'))
            if str(request.url).endswith('/audio/transcriptions'):
                self.assertIn(b'whisper-large-v3-turbo', request.content)
                self.assertIn(b'RIFF', request.content)
                return httpx.Response(200, json={'text': 'Hello world'})
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(raw_evaluation())}}]})
        RealClient = httpx.Client
        def mock_client(*args, **kwargs):
            return RealClient(transport=httpx.MockTransport(handler), **kwargs)
        with patch('app.coach.httpx.Client', side_effect=mock_client):
            result = _groq_request(self.settings, 'audio/transcriptions',
                form_data={'model': 'whisper-large-v3-turbo', 'language': 'en'},
                files={'file': ('practice.wav', audio_wave(), 'audio/wav')})
            self.assertEqual(result['text'], 'Hello world')
            result2 = _groq_request(self.settings, 'chat/completions', payload={'model': 'openai/gpt-oss-20b'})
        self.assertIn('choices', result2)
        self.assertEqual(len(seen), 2)

    def test_http_429_response_does_not_leak_sensitive_body(self):
        RealClient = httpx.Client
        def handler(request):
            return httpx.Response(429, json={'error': 'sensitive gsk_nope'}, request=request)
        def mock_client(*args, **kwargs):
            return RealClient(transport=httpx.MockTransport(handler), **kwargs)
        with patch('app.coach.httpx.Client', side_effect=mock_client):
            with self.assertRaises(AIUnavailable) as context:
                evaluate(BY_ID['p1-study-1'],
                         'I enjoy reading books because stories help me understand new ideas.', self.settings)
        self.assertIn('rate limit', str(context.exception).lower())
        self.assertNotIn('gsk_nope', str(context.exception))

    def test_no_key_no_cloud_transcription(self):
        with self.assertRaises(TranscriptionUnavailable):
            transcribe(audio_wave(), Settings(data_dir=Path('/tmp')), True)


class DatabaseTests(unittest.TestCase):
    def test_roundtrip_and_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / 'subdir' / 'test.db')
            entry = {
                'id': 'attempt-1', 'session_id': 'session-1',
                'created_at': '2026-10-30T08:00:00+00:00', 'question_id': 'p1-study-1',
                'part': 1, 'topic': 'Study & Work', 'prompt': 'Q?',
                'transcript': 'A sample text.', 'transcription_source': 'manual',
                'duration_seconds': 10.0, 'metrics': {'word_count': 3},
                'evaluation': None, 'ai_error': 'AI disabled', 'cloud_audio_used': False,
                'estimated_band': None, 'language_estimate_band': None,
            }
            db.add(entry)
            self.assertEqual(db.get('attempt-1')['transcript'], 'A sample text.')
            self.assertEqual(db.list()[0]['metrics']['word_count'], 3)
            self.assertEqual(db.stats()['total_attempts'], 1)
            self.assertEqual(db.delete_all(), 1)
            self.assertEqual(db.stats()['total_attempts'], 0)

    def test_migrates_old_v1_database_without_erasing_records(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'practice.db'
            connection = sqlite3.connect(path)
            connection.execute('''CREATE TABLE attempts (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, created_at TEXT NOT NULL,
                question_id TEXT NOT NULL, part INTEGER NOT NULL, topic TEXT NOT NULL,
                prompt TEXT NOT NULL, transcript TEXT NOT NULL, transcription_source TEXT NOT NULL,
                duration_seconds REAL NOT NULL, metrics_json TEXT NOT NULL, evaluation_json TEXT,
                ai_error TEXT, cloud_audio_used INTEGER NOT NULL DEFAULT 0, estimated_band REAL)''')
            connection.execute('''INSERT INTO attempts VALUES (
                'old','session','2026-10-30T08:00:00+00:00','p1-study-1',1,'Study & Work',
                'Q?','My original answer','manual',10,'{}',null,null,0,null)''')
            connection.commit()
            connection.close()
            db = Database(path)
            self.assertEqual(db.stats()['total_attempts'], 1)
            self.assertIn('language_estimate_band', db.get('old'))
            self.assertEqual(db.get('old')['transcript'], 'My original answer')


if __name__ == '__main__':
    unittest.main()
