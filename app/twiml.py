"""TwiML: the XML that tells Twilio what to say and listen for on a call."""

from xml.sax.saxutils import escape, quoteattr

VOICES = {
    "en": {"voice": "Polly.Joanna", "language": "en-US"},
    "es": {"voice": "Polly.Lupe", "language": "es-US"},
}


def voice_for(lang: str) -> dict:
    return VOICES.get(lang, VOICES["en"])


def say(text: str, lang: str = "en") -> str:
    v = voice_for(lang)
    return f'<Say voice={quoteattr(v["voice"])} language={quoteattr(v["language"])}>{escape(text)}</Say>'


def response(*parts: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(parts) + "</Response>"


def gather(prompt: str, action_url: str, lang: str = "en", timeout: int = 6) -> str:
    v = voice_for(lang)
    hints = "yes, okay, fine, I'm okay, help, I need help" if lang == "en" else "sí, bien, estoy bien, ayuda, necesito ayuda"
    return (
        f'<Gather input="dtmf speech" numDigits="1" timeout="{timeout}" speechTimeout="auto" '
        f'language={quoteattr(v["language"])} hints={quoteattr(hints)} '
        f'action={quoteattr(action_url)} method="POST" actionOnEmptyResult="false">'
        f"{say(prompt, lang)}</Gather>"
    )


def redirect(url: str) -> str:
    return f'<Redirect method="POST">{escape(url)}</Redirect>'


def hangup() -> str:
    return "<Hangup/>"


def pause(seconds: int = 1) -> str:
    return f'<Pause length="{int(seconds)}"/>'
