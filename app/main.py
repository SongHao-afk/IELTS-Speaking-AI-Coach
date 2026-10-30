"""Speakly v2.3: local IELTS Speaking with transparent, Analyze-triggered Groq STT."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .audio import InvalidAudio, transcript_metrics, wav_metrics
from .coach import AIUnavailable, TranscriptionUnavailable, evaluate, has_whisper, transcribe
from .config import PROJECT_ROOT, Settings, load_settings
from .db import Database
from .questions import BY_ID, QUESTIONS, all_questions, mock_questions

WEB_DIR = PROJECT_ROOT / 'web'


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    database = Database(settings.data_dir / 'practice.db')
    app = FastAPI(title='Speakly | IELTS Speaking Coach', version='2.3.0',
                  description='Optional Groq STT/feedback. Unofficial language-only estimates, not IELTS scores.')

    @app.get('/api/health')
    def health():
        return {'ok': True, 'version': '2.3.0'}

    @app.get('/api/config')
    def config():
        return {
            'ai_enabled': settings.ai_enabled,
            'llm_provider': settings.llm_provider,
            'local_stt_available': has_whisper(),
            'cloud_stt_available': settings.cloud_stt_available,
            'stt_provider': settings.stt_provider,
            'stt_available': (settings.stt_provider in ('auto', 'whisper') and has_whisper())
                             or settings.cloud_stt_available,
            'model': settings.groq_model if settings.ai_enabled else None,
            'stt_model': settings.groq_stt_model if settings.cloud_stt_available else None,
            'audio_storage': False,
            'disclaimer': 'No pronunciation scoring. Clicking Analyze permits Groq Whisper upload when transcript is empty.',
        }

    @app.get('/api/questions')
    def questions(part: int | None = Query(default=None, ge=1, le=3), topic: str | None = None):
        items = all_questions(part=part, topic=topic)
        return {'questions': items, 'total': len(items),
                'topics': sorted(set(q.topic for q in QUESTIONS if part is None or q.part == part))}

    @app.get('/api/mock')
    def mock(seed: int | None = None):
        return {'questions': mock_questions(seed), 'note': '5 Part 1, 1 Part 2, 4 Part 3 practice prompts.'}

    @app.get('/api/stats')
    def stats():
        return database.stats()

    @app.get('/api/attempts')
    def attempts(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
        return {'attempts': database.list(limit, offset)}

    @app.get('/api/attempts/{attempt_id}')
    def attempt(attempt_id: str):
        item = database.get(attempt_id)
        if not item:
            raise HTTPException(status_code=404, detail='Attempt not found.')
        return item

    @app.post('/api/attempts/{attempt_id}/retry-feedback')
    async def retry_feedback(attempt_id: str):
        # Regrade the stored transcript only. Never retranscribe or upload audio here.
        existing = database.get(attempt_id)
        if existing is None:
            raise HTTPException(status_code=404, detail='Attempt not found.')
        if not settings.ai_enabled:
            raise HTTPException(status_code=503, detail='AI coach not configured. Add GROQ_API_KEY to .env.')
        question = BY_ID.get(existing['question_id'])
        if question is None:
            raise HTTPException(status_code=422, detail='Original question no longer exists.')
        audio_stats = existing['metrics'].get('audio')
        try:
            assessment = await run_in_threadpool(evaluate, question, existing['transcript'], settings, audio_stats)
        except AIUnavailable as exc:
            database.update_feedback(attempt_id, None, str(exc))
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        database.update_feedback(attempt_id, assessment, None)
        return database.get(attempt_id)

    @app.delete('/api/attempts')
    def clear_history():
        return {'deleted': database.delete_all()}

    @app.post('/api/attempts', status_code=201)
    async def create_attempt(
        question_id: str = Form(...),
        transcript: str = Form(''),
        duration_seconds: float = Form(0, ge=0, le=210),
        session_id: str = Form(''),
        allow_cloud_audio: bool = Form(False),
        audio: UploadFile | None = File(default=None),
    ):
        question = BY_ID.get(question_id)
        if question is None:
            raise HTTPException(404, 'Invalid question ID.')
        transcript = transcript.strip()
        if len(transcript) > 10000:
            raise HTTPException(422, 'Transcript must be 10,000 characters or fewer.')
        if session_id and (len(session_id) > 64 or not all(ch.isalnum() or ch in '-_' for ch in session_id)):
            raise HTTPException(422, 'Invalid session ID.')

        audio_bytes = None
        audio_stats = None
        if audio is not None and audio.filename:
            try:
                audio_bytes = await audio.read(settings.max_audio_bytes + 1)
            finally:
                await audio.close()
            if len(audio_bytes) > settings.max_audio_bytes:
                raise HTTPException(413, 'Recording exceeds the 16 MB application limit.')
            try:
                audio_stats = wav_metrics(audio_bytes)
            except InvalidAudio as exc:
                raise HTTPException(422, str(exc)) from exc
            if audio_stats['active_seconds'] < 0.2 or audio_stats['speech_ratio'] < 0.02:
                raise HTTPException(422, 'The recording appears silent. Check microphone permission and try again.')
            duration_seconds = audio_stats['duration_seconds']

        source = 'manual'
        if not transcript:
            if not audio_bytes:
                raise HTTPException(422, 'Record an answer or enter its transcript before evaluation.')
            try:
                transcript, source = await run_in_threadpool(transcribe, audio_bytes, settings, allow_cloud_audio)
            except (TranscriptionUnavailable, AIUnavailable) as exc:
                raise HTTPException(422, str(exc)) from exc
        if not transcript.strip():
            raise HTTPException(422, 'No spoken or written answer detected.')
        if len(transcript) > 10000:
            raise HTTPException(422, 'Transcription is too long (maximum 10,000 characters).')

        metrics = transcript_metrics(transcript, duration_seconds, audio_stats)
        assessment = None
        ai_error = None
        if settings.ai_enabled:
            try:
                assessment = await run_in_threadpool(evaluate, question, transcript, settings, audio_stats)
            except AIUnavailable as exc:
                ai_error = str(exc)
        else:
            ai_error = 'AI coach not configured. Add GROQ_API_KEY to .env and restart.'

        entry = {
            'id': str(uuid.uuid4()),
            'session_id': session_id or str(uuid.uuid4()),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'question_id': question.id,
            'part': question.part,
            'topic': question.topic,
            'prompt': question.prompt,
            'transcript': transcript,
            'transcription_source': source,
            'duration_seconds': round(float(duration_seconds), 2),
            'metrics': metrics,
            'evaluation': assessment,
            'ai_error': ai_error,
            'cloud_audio_used': source == 'groq_whisper',
            'estimated_band': None,  # Never emit an IELTS overall score from text-only Groq.
            'language_estimate_band': assessment['language_estimate_band'] if assessment else None,
        }
        database.add(entry)
        return entry

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / 'index.html')

    app.mount('/static', StaticFiles(directory=WEB_DIR), name='static')
    return app


app = create_app()
