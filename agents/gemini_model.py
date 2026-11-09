"""Gemini text-only planner. Model proposals are untrusted data.

Uses the Gemini REST API through the standard library, so no extra dependency is needed.
Set GEMINI_API_KEY (and optionally GEMINI_MODEL). The key is sent in a header and is
never included in error messages.
"""
import json
import os
import urllib.error
import urllib.request

from agents.oci_model import OCIPlanner

DEFAULT_MODEL = 'gemini-3.5-flash'
API_ROOT = 'https://generativelanguage.googleapis.com/v1beta/models'


class GeminiPlanner(OCIPlanner):
    """Same prompts and strict output parsing as OCIPlanner; only the model call differs."""
    name = 'live'

    def __init__(self, api_key=None, model_id=None, domain='ticket', opener=None):
        if domain not in ('ticket', 'email'):
            raise ValueError('Unknown domain')
        self.domain = domain
        self._api_key = api_key or os.environ.get('GEMINI_API_KEY')
        self.model_id = model_id or os.environ.get('GEMINI_MODEL') or DEFAULT_MODEL
        self.model = self.model_id
        if not self._api_key:
            raise ValueError('Set GEMINI_API_KEY')
        self._open = opener or urllib.request.urlopen

    def _chat(self, message, max_tokens):
        config = {'temperature': 0, 'maxOutputTokens': max(max_tokens, 1024)}
        if 'flash' in self.model_id:
            # Thinking tokens would otherwise eat the output budget on 2.5 Flash.
            config['thinkingConfig'] = {'thinkingBudget': 0}
        body = json.dumps({
            'contents': [{'role': 'user', 'parts': [{'text': message}]}],
            'generationConfig': config,
        }).encode()
        req = urllib.request.Request(
            f'{API_ROOT}/{self.model_id}:generateContent', data=body, method='POST',
            headers={'Content-Type': 'application/json', 'x-goog-api-key': self._api_key})
        try:
            with self._open(req, timeout=30) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = ''
            try:
                detail = json.loads(exc.read()).get('error', {}).get('message', '')[:300]
            except Exception:
                pass
            raise RuntimeError(f'Gemini request failed (HTTP {exc.code}): {detail}'.rstrip(': ')) from None
        try:
            parts = data['candidates'][0]['content']['parts']
            return ''.join(p.get('text', '') for p in parts)
        except (KeyError, IndexError, TypeError):
            # Blocked or empty output: fail closed (the parser rejects an empty proposal).
            return ''