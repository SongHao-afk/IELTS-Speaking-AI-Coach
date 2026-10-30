"""Server-only settings for Groq AI. Never expose keys in HTTP responses."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    path = PROJECT_ROOT / '.env'
    if path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=path, override=False)
        except ImportError:
            pass


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    groq_api_key: str = ''
    groq_model: str = 'openai/gpt-oss-20b'
    groq_stt_model: str = 'whisper-large-v3-turbo'
    llm_provider: str = 'groq'
    stt_provider: str = 'groq'
    whisper_model: str = 'base.en'
    max_audio_bytes: int = 16 * 1024 * 1024

    @property
    def ai_enabled(self) -> bool:
        return self.llm_provider == 'groq' and bool(self.groq_api_key)

    @property
    def cloud_stt_available(self) -> bool:
        return self.stt_provider in ('groq', 'auto') and bool(self.groq_api_key)


def load_settings() -> Settings:
    _load_dotenv()
    stt = os.getenv('STT_PROVIDER', 'groq').lower().strip()
    if stt not in ('auto', 'whisper', 'groq', 'none'):
        raise ValueError('STT_PROVIDER must be auto, whisper, groq or none')
    llm = os.getenv('LLM_PROVIDER', 'groq').lower().strip()
    if llm not in ('groq', 'none'):
        raise ValueError('LLM_PROVIDER must be groq or none')
    data_dir = Path(os.getenv('APP_DATA_DIR', './data')).expanduser()
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    return Settings(
        data_dir=data_dir.resolve(),
        groq_api_key=os.getenv('GROQ_API_KEY', '').strip(),
        groq_model=os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b').strip(),
        groq_stt_model=os.getenv('GROQ_STT_MODEL', 'whisper-large-v3-turbo').strip(),
        llm_provider=llm,
        stt_provider=stt,
        whisper_model=os.getenv('WHISPER_MODEL', 'base.en').strip(),
    )
