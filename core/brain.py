"""
core/brain.py — Flash Brain (Final)

Architecture:
  1. QuickRouter — high-confidence deterministic patterns only
     Catches: chatgpt/claude type-in, explicit YouTube search, named sites,
              arbitrary .com URLs, weather, time. NOTHING ELSE.
     Wrong match = worse than no match. When in doubt, let LLM decide.

  2. Atomic execution — weather/time run inline and return complete answers.
     No two-turn "checking..." then "done?" ever again.

  3. Ollama native tool calling — structured tool_calls[], not text parsing.
     Temperature 0.0 for tool calls (deterministic). LLM either calls a tool
     or answers directly. Never both. Never "I am just a tool."

  4. Smart TTS formatting — system specs spoken as natural sentences.
     Raw data NEVER reaches the speaker. Everything is summarised first.

  5. Rolling context summary — at 14 turns, oldest 8 compressed to 2 sentences.
     Context never lost. Long sessions stay coherent.

  6. Personality — Flash is confident, witty, brief. Not a customer service bot.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

from core.gpu_lock import GPU_LOCK

log = logging.getLogger('flash.brain')

_HERE = Path(__file__).parent.parent.resolve()
CONFIG_PATH = _HERE / 'config' / 'config.json'

SITES = {
    'youtube': 'https://www.youtube.com',
    'amazon': 'https://www.amazon.in',
    'flipkart': 'https://www.flipkart.com',
    'gmail': 'https://mail.google.com',
    'google': 'https://www.google.com',
    'github': 'https://www.github.com',
    'netflix': 'https://www.netflix.com',
    'spotify': 'https://open.spotify.com',
    'chatgpt': 'https://chatgpt.com',
    'claude': 'https://claude.ai',
    'perplexity': 'https://www.perplexity.ai',
    'linkedin': 'https://www.linkedin.com',
    'twitter': 'https://twitter.com',
    'reddit': 'https://www.reddit.com',
    'maps': 'https://maps.google.com',
    'wikipedia': 'https://en.wikipedia.org',
    'stackoverflow': 'https://stackoverflow.com',
    'instagram': 'https://www.instagram.com',
    'whatsapp': 'https://web.whatsapp.com',
    'hotstar': 'https://www.hotstar.com',
    'jiocinema': 'https://www.jiocinema.com',
    'primevideo': 'https://www.primevideo.com',
}


def _cfg() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════════════
#  QUICK ROUTER — only patterns we are 100% certain about
# ══════════════════════════════════════════════════════════════════════════════
class QuickRouter:
    """
    Catches high-confidence intents before the LLM sees them.
    Rule: if there is ANY ambiguity, return None and let the LLM decide.
    Bad match = user frustrated. No match = LLM handles it fine.
    """

    def match(self, text: str) -> Optional[dict]:
        t = text.lower().strip()

        # ── Type into AI site: "search/ask X on chatgpt/claude" ──────────
        for pat, url in [
            (r'(?:search|ask|type|query|write)\s+(.+?)\s+on\s+chatgpt', 'https://chatgpt.com'),
            (r'(?:search|ask|type|query|write)\s+(.+?)\s+on\s+claude',  'https://claude.ai'),
            (r'(?:search|ask|type|query|write)\s+(.+?)\s+on\s+perplexity', 'https://www.perplexity.ai'),
            (r'open\s+chatgpt\s+(?:and\s+)?(?:ask|search|write|type)\s+(.+)', 'https://chatgpt.com'),
            (r'open\s+claude\s+(?:and\s+)?(?:ask|search|write|type)\s+(.+)',  'https://claude.ai'),
            (r'ask\s+chatgpt\s+(?:to\s+)?(.+)', 'https://chatgpt.com'),
            (r'ask\s+claude\s+(?:to\s+)?(.+)',  'https://claude.ai'),
        ]:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                return {'action': 'open_url_and_type', 'url': url,
                        'query': m.group(1).strip()}

        # ── Explicit YouTube search (NOT just "play X") ───────────────────
        m = re.search(r'(?:search|find|look\s*up)\s+(.+?)\s+on\s+youtube', t)
        if m:
            q = m.group(1).strip().replace(' ', '+')
            return {'action': 'open_url',
                    'url': f'https://www.youtube.com/results?search_query={q}'}

        # ── Named site: "open youtube" / "open amazon" ────────────────────
        site_list = '|'.join(SITES.keys())
        m = re.search(rf'^open\s+({site_list})$', t)
        if m:
            return {'action': 'open_url', 'url': SITES[m.group(1).lower()]}

        # ── Arbitrary URL: "open monkeytype.com" ─────────────────────────
        m = re.search(
            r'^open\s+((?:https?://)?[\w\-]+\.'
            r'(?:com|org|net|in|io|co|dev|app|ai|tv|edu|gov)\S*)\s*$', t)
        if m:
            url = m.group(1)
            if not url.startswith('http'):
                url = 'https://' + url
            return {'action': 'open_url', 'url': url}

        # ── Google search: "google X" / "search for X" ────────────────────
        m = re.search(r'^(?:google|search\s+for|search)\s+(.+)$', t)
        if m and 'on ' not in m.group(1):
            q = m.group(1).strip().replace(' ', '+')
            return {'action': 'open_url',
                    'url': f'https://www.google.com/search?q={q}'}

        # ── Weather (atomic) ──────────────────────────────────────────────
        if re.search(
            r"(?:what(?:s|'?s|\s+is)?)\s+(?:the\s+)?weather"
            r"|(?:how(?:s|'?s|\s+is)?)\s+(?:the\s+)?weather"
            r"|weather\s*(?:today|now|outside|update|like|report)?"
            r"|is\s+it\s+(?:raining|sunny|hot|cold|cloudy|windy)", t):
            return {'action': 'get_weather'}

        m = re.search(
            r'(?:good\s+(?:weather\s+)?for|is\s+(?:the\s+)?weather\s+good\s+for'
            r'|should\s+i\s+go\s+(?:for\s+)?(?:a\s+)?|can\s+i\s+go\s+(?:for\s+)?(?:a\s+)?)'
            r'\s*(.+)', t)
        if m:
            return {'action': 'weather_activity',
                    'activity': m.group(1).strip()}

        # ── Time (atomic) ─────────────────────────────────────────────────
        if re.search(
            r"(?:what(?:s|'?s|\s+is)?)\s+(?:the\s+)?(?:time|date|day)"
            r"|current\s+(?:time|date)|what\s+time\s+is\s+it", t):
            return {'action': 'get_time'}

        return None  # LLM handles everything else


# ══════════════════════════════════════════════════════════════════════════════
#  SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════
def _sys(name: str, user: str, city: str) -> str:
    return f"""\
You are {name} — {user}'s personal AI assistant running locally on Ubuntu in {city}.

PERSONALITY:
- Sharp, fast, direct. Like a brilliant friend who respects your time.
- When asked "how are you" → answer briefly and ask how you can help.
- When asked your name → "{name}". Never call yourself "just a tool" or "just an AI".
- 1-2 sentences MAX for replies. No padding, no filler.

TOOL RULES:
- If {user} asks you to DO something → use a tool. Don't describe what you'll do.
- If {user} asks a QUESTION → answer it directly. Don't use a tool unless you need data.
- If {user} says "done?" or "did it work?" → reference your last tool result from history.
- "it", "that", "this" → resolve from conversation history. Never ask for clarification.
- After you open YouTube → if user says "play it"/"play one"/"click play" → use click_play.

TOOLS AVAILABLE:
  open_url          → browser: websites, YouTube, Google
  run_command       → bash: any shell command
  get_system_info   → hardware stats (spoken as natural sentences)
  open_app          → launch desktop apps
  create_file       → create files with content
  read_screen       → screenshot + OCR: "what's on screen", "read this error"
  keyboard_shortcut → close tab=ctrl+w, close window=alt+f4, new tab=ctrl+t
  type_text         → type into focused window
  click_play        → click first video on YouTube results page
  vscode_file       → read currently open VS Code file
  get_active_window → what app is focused
  play_youtube      → search YouTube and play first result with mpv (best for music/video)

CRITICAL — SYSTEM SPECS:
When get_system_info runs, the result is raw data like "CPU 2.4% — RAM 6686/15623 MB".
NEVER speak this raw. Convert it: "Your CPU is at 2%, RAM is 6.6 GB used of 16, disk is 77 of 238 GB."
"""


# ══════════════════════════════════════════════════════════════════════════════
#  DATA → SPOKEN LANGUAGE FORMATTERS
# ══════════════════════════════════════════════════════════════════════════════
def _format_system_info(raw: str) -> str:
    """Convert raw system info string to natural spoken English."""
    try:
        # Parse: "CPU 2.4% — RAM 6686/15623 MB (42.8%) — Disk 77/238 GB..."
        cpu = re.search(r'CPU\s+([\d.]+)%', raw)
        ram_used = re.search(r'RAM\s+([\d.]+)/[\d.]+ MB', raw)
        ram_total = re.search(r'RAM\s+[\d.]+/([\d.]+) MB', raw)
        disk_used = re.search(r'Disk\s+([\d.]+)/[\d.]+ GB', raw)
        disk_total = re.search(r'Disk\s+[\d.]+/([\d.]+) GB', raw)
        vram_used = re.search(r'VRAM\s+([\d.]+)/([\d.]+)\s*MB', raw)
        temp = re.search(r'Temp\s+([\d.]+)°C', raw)

        parts = []
        if cpu:
            parts.append(f"CPU is at {float(cpu.group(1)):.0f}%")
        if ram_used and ram_total:
            used_gb = float(ram_used.group(1)) / 1024
            total_gb = float(ram_total.group(1)) / 1024
            parts.append(f"RAM is {used_gb:.1f} of {total_gb:.0f} GB used")
        if disk_used and disk_total:
            parts.append(f"disk is {disk_used.group(1)} of {disk_total.group(1)} GB")
        if vram_used:
            parts.append(f"GPU VRAM {vram_used.group(1)} of {vram_used.group(2)} MB")
        if temp:
            parts.append(f"GPU temp {temp.group(1)}°C")

        if parts:
            return '. '.join(parts) + '.'
    except Exception:
        pass
    # Fallback: extract just numbers, skip separators
    clean = re.sub(r'\s*—\s*', '. ', raw)
    clean = re.sub(r'\([\d.]+%\)', '', clean)
    return clean[:300]


def _format_for_speech(text: str, query: str = '') -> str:
    """
    Convert any tool output to something Piper can speak naturally.
    Key insight: Piper speaks sentences well. It speaks raw data poorly.
    """
    if not text:
        return ''

    # System info — always convert to natural sentences
    if 'CPU' in text and 'RAM' in text and 'MB' in text:
        return _format_system_info(text)

    # File paths — shorten
    text = re.sub(r'/home/[\w-]+/', '~/', text)

    # URLs — say domain only
    text = re.sub(r'https?://(?:www\.)?([^/\s]+)\S*',
                  lambda m: m.group(1), text)

    # Strip markdown
    text = re.sub(r'```[\s\S]*?```', 'code block', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-•*]\s+', '', text, flags=re.MULTILINE)

    # Collapse whitespace
    text = re.sub(r'\n+', '. ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\.{2,}', '.', text)

    # Hard cap — Piper speaks ~120 chars cleanly
    # Split at sentence boundary near 200 chars
    if len(text) > 220:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        result = ''
        for s in sentences:
            if len(result) + len(s) < 220:
                result += (' ' if result else '') + s
            else:
                break
        text = result or text[:220]

    return text.strip()


# ══════════════════════════════════════════════════════════════════════════════
#  BRAIN
# ══════════════════════════════════════════════════════════════════════════════
class Brain:

    def __init__(self, model: str = 'qwen2.5:3b', desktop=None):
        cfg = _cfg()
        self.model      = cfg.get('model', model)
        self.model_code = cfg.get('model_code', 'qwen2.5-coder:3b')
        self.desktop    = desktop
        self.history    = []   # full conversation history
        self.router     = QuickRouter()
        self._name      = cfg.get('assistant_name', 'Vox')
        self._user      = cfg.get('user_name', 'User')
        self._city      = cfg.get('user_city', 'New York')
        self._verify()

    def _verify(self):
        try:
            import requests
            requests.get('http://localhost:11434', timeout=3)
            log.info(f"Ollama OK — {self._name} for {self._user} | {self.model}")
        except Exception as e:
            log.error(f"Ollama: {e}")

    def reload_persona(self):
        cfg = _cfg()
        self._name  = cfg.get('assistant_name', 'Vox')
        self._user  = cfg.get('user_name', 'User')
        self._city  = cfg.get('user_city', 'New York')
        self.model  = cfg.get('model', self.model)

    # ── Public entry point ────────────────────────────────────────────────────
    def think(self, user_input: str,
              memory_context: str = '') -> tuple[str, list]:
        """
        Returns (spoken_reply, list_of_actions).
        spoken_reply is ALWAYS formatted for TTS — no raw data, no markdown.
        """
        # Rolling context summary — keep history manageable
        self._maybe_summarise()

        # Quick router — atomic or pass-through
        intent = self.router.match(user_input)
        if intent:
            action = intent.get('action')

            # Fully atomic — answer inline, no tool executor round-trip
            if action == 'get_weather' and self.desktop:
                raw = self.desktop.get_weather_summary()
                self._add(user_input, raw)
                return raw, []

            if action == 'weather_activity' and self.desktop:
                raw = self.desktop.is_good_for_activity(
                    intent.get('activity', 'going outside'))
                self._add(user_input, raw)
                return raw, []

            if action == 'get_time' and self.desktop:
                t = self.desktop.get_current_time()
                self._add(user_input, t)
                return t, []

            # Non-atomic — hand to executor
            spoken = self._intent_spoken(intent)
            self._add(user_input, spoken)
            return spoken, [intent]

        # LLM
        return self._llm(user_input, memory_context)

    # ── LLM call ─────────────────────────────────────────────────────────────
    def _llm(self, user_input: str,
             memory_context: str) -> tuple[str, list]:
        import requests as req

        content = user_input
        if memory_context:
            content = f"[Relevant memory: {memory_context}]\n\n{user_input}"

        self.history.append({'role': 'user', 'content': content})

        model = self._pick_model(user_input)
        msgs  = [{'role': 'system',
                  'content': _sys(self._name, self._user, self._city)}]
        msgs += self.history[-18:]

        try:
            with GPU_LOCK:
                r = req.post('http://localhost:11434/api/chat', json={
                    'model': model,
                    'messages': msgs,
                    'tools': self._schemas(),
                    'stream': False,
                    'options': {
                        'temperature': 0.0,   # deterministic tool calls
                        'num_predict': 250,
                        'num_ctx': 4096,
                        'repeat_penalty': 1.1,
                    }
                }, timeout=45)
            r.raise_for_status()
            msg = r.json().get('message', {})

            tool_calls = msg.get('tool_calls', [])
            text       = (msg.get('content') or '').strip()

            if tool_calls:
                actions = []
                for tc in tool_calls:
                    fn = tc.get('function', {})
                    name = fn.get('name', '')
                    args = fn.get('arguments', {})
                    if name:
                        actions.append({'action': name, **args})
                        log.info(f"Tool call: {name}({args})")
                spoken = self._actions_spoken(actions, user_input)
                self.history.append({'role': 'assistant', 'content': spoken})
                return spoken, actions

            # Plain text response
            spoken = self._clean(text)
            if not spoken:
                spoken = "I'm not sure how to help with that."
            self.history.append({'role': 'assistant', 'content': spoken})
            return spoken, []

        except Exception as e:
            log.error(f"LLM error: {e}")
            return self._fallback(user_input), []

    def _fallback(self, query: str) -> str:
        """Minimal fallback when main LLM call fails."""
        import requests as req
        try:
            with GPU_LOCK:
                r = req.post('http://localhost:11434/api/chat', json={
                    'model': self.model,
                    'messages': [
                        {'role': 'system',
                        'content': f"You are {self._name}. Answer in 1 sentence."},
                        {'role': 'user', 'content': query}
                    ],
                    'stream': False,
                    'options': {'temperature': 0.3, 'num_predict': 80}
                }, timeout=20)
            r.raise_for_status()
            return self._clean(
                r.json().get('message', {}).get('content', '')
            ) or "Sorry, I had trouble with that."
        except Exception:
            return "Can't reach Ollama right now."

    # ── After tool runs — summarise result for TTS ────────────────────────────
    def synthesize(self, original_query: str,
                   initial_response: str,
                   tool_outputs: list) -> str:
        """
        Convert tool output to something speakable.
        Never return raw data to the TTS.
        """
        if not tool_outputs:
            return initial_response or 'Done.'

        combined = '\n'.join(str(o) for o in tool_outputs)

        # System info — always convert
        if 'CPU' in combined and 'RAM' in combined:
            return _format_system_info(combined)

        # Short outputs — clean and speak
        if len(combined) < 180:
            return _format_for_speech(combined, original_query)

        # Long outputs — summarise with LLM
        try:
            import requests as req
            r = req.post('http://localhost:11434/api/chat', json={
                'model': self.model,
                'messages': [
                    {'role': 'system',
                     'content': (f"You are {self._name}. "
                                 f"Summarise data for {self._user} in 1-2 "
                                 f"spoken sentences. Include key numbers. "
                                 f"No markdown. No filler words.")},
                    {'role': 'user',
                     'content': (f"Query: {original_query}\n"
                                 f"Data:\n{combined[:600]}")}
                ],
                'stream': False,
                'options': {'temperature': 0.2, 'num_predict': 100}
            }, timeout=25)
            r.raise_for_status()
            result = r.json().get('message', {}).get('content', '').strip()
            return self._clean(result) or initial_response or 'Done.'
        except Exception:
            return _format_for_speech(combined[:200], original_query)

    def inject_tool_result(self, name: str, result: str):
        """Store tool output in history so next turn can reference it."""
        if result and result.strip():
            # Store human-readable version for context
            spoken_result = _format_for_speech(result, name)
            self.history.append({
                'role': 'user',
                'content': f"[{name} completed. Result: {spoken_result}]"
            })
            self.history.append({
                'role': 'assistant',
                'content': 'Done.'
            })

    # ── Context management ────────────────────────────────────────────────────
    def _maybe_summarise(self):
        """
        Rolling summary — when history gets long, compress the oldest turns.
        This prevents context window overflow and keeps sessions coherent.
        """
        if len(self.history) < 14:
            return
        # Summarise the oldest 8 turns
        to_compress = self.history[:8]
        compressed_text = '\n'.join(
            f"{m['role'].upper()}: {m['content'][:100]}"
            for m in to_compress
        )
        try:
            import requests as req
            with GPU_LOCK:
                r = req.post('http://localhost:11434/api/chat', json={
                    'model': self.model,
                    'messages': [
                        {'role': 'system',
                        'content': 'Summarise this conversation in 2 sentences. Be factual.'},
                        {'role': 'user', 'content': compressed_text}
                    ],
                    'stream': False,
                    'options': {'temperature': 0.0, 'num_predict': 80}
                }, timeout=15)
            r.raise_for_status()
            summary = r.json().get('message', {}).get('content', '').strip()
            if summary:
                # Replace oldest 8 turns with summary, keep rest
                self.history = [
                    {'role': 'user', 'content': f'[Earlier summary: {summary}]'},
                    {'role': 'assistant', 'content': 'Understood.'}
                ] + self.history[8:]
                log.info("Context compressed.")
        except Exception as e:
            log.debug(f"Summary failed (non-critical): {e}")
            # Just trim instead
            self.history = self.history[8:]

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _pick_model(self, text: str) -> str:
        code_kw = ['code', 'python', 'javascript', 'typescript', 'bug',
                   'error in my', 'fix this', 'syntax', 'function',
                   'class ', 'debug', 'compile', 'git ', 'npm ', 'pip ']
        if any(k in text.lower() for k in code_kw):
            log.info(f"Code model selected: {self.model_code}")
            return self.model_code
        return self.model

    def _intent_spoken(self, intent: dict) -> str:
        a = intent.get('action', '')
        if a == 'open_url':
            url = intent.get('url', '')
            if 'youtube.com/results' in url:
                q = url.split('search_query=')[-1].replace('+', ' ')
                return f"Searching YouTube for {q}."
            domain = url.split('//')[-1].split('/')[0].replace('www.', '')
            return f"Opening {domain}."
        if a == 'open_url_and_type':
            domain = intent.get('url', '').split('//')[-1].split('/')[0].replace('www.', '')
            q = intent.get('query', '')
            return f"Opening {domain} and searching for {q}."
        if a == 'play_youtube':
            return f"Playing {intent.get('query', 'video')}."
        return "On it."

    def _actions_spoken(self, actions: list, query: str) -> str:
        if not actions:
            return 'Done.'
        parts = []
        for a in actions:
            name = a.get('action', '')
            if name == 'open_url':
                url = a.get('url', '')
                if 'youtube' in url:
                    q = url.split('search_query=')[-1].replace('+', ' ')
                    parts.append(f"Searching YouTube for {q}")
                else:
                    d = url.split('//')[-1].split('/')[0].replace('www.', '')
                    parts.append(f"Opening {d}")
            elif name == 'keyboard_shortcut':
                parts.append(f"Pressing {a.get('keys', '')}")
            elif name == 'click_play':
                parts.append("Playing")
            elif name == 'play_youtube':
                parts.append(f"Playing {a.get('query', 'video')}")
            elif name == 'read_screen':
                parts.append("Reading screen")
            elif name == 'get_system_info':
                parts.append("Checking specs")
            elif name == 'run_command':
                parts.append("Running command")
            elif name == 'vscode_file':
                parts.append("Reading your file")
            else:
                parts.append(name.replace('_', ' '))
        return ', '.join(parts) + '.'

    def _clean(self, text: str) -> str:
        """Strip AI meta-commentary, planning language, tail questions."""
        if not text:
            return ''

        # Remove sentences containing meta-commentary
        sentences = re.split(r'(?<=[.!?])\s+', text)
        bad_phrases = [
            "just an ai", "just a tool", "just an assistant",
            "language model", "as an ai", "i cannot directly",
            "not able to", "don't have the ability", "cannot access",
        ]
        clean_sentences = []
        for sent in sentences:
            sl = sent.lower()
            if not any(phrase in sl for phrase in bad_phrases):
                clean_sentences.append(sent)
        text = ' '.join(clean_sentences).strip()

        # Remove planning prefixes from start
        filler_pats = [
            r"^Sure[,!]?\s+", r"^Of course[,!]?\s+", r"^Let me\s+",
            r"^I will\s+", r"^I'll go ahead\s+", r"^I'm going to\s+",
            r"^Certainly[,!]?\s+", r"^Absolutely[,!]?\s+",
            r"^One moment[.,]?\s*", r"^Please wait[.,]?\s*",
            r"^I'll\s+",
        ]
        for p in filler_pats:
            text = re.sub(p, '', text, flags=re.IGNORECASE).strip()

        # Remove trailing helper questions / location mentions
        tail_pats = [
            r"\s*How (?:can|else may|may) I (?:assist|help) you[^?]*\??\s*$",
            r"\s*Is there (?:anything|something)[^?]*\??\s*$",
            r"\s*What else[^?]*\??\s*$",
            r"\s*\(timezone:[^)]*\)\s*$",
            r"\s*in [a-zA-Z\s]+[,.]?\s*$",  # Generic city/location cleanup
        ]
        for p in tail_pats:
            text = re.sub(p, '', text, flags=re.IGNORECASE).strip()

        # Cap at 2 sentences
        if len(text) > 350:
            sents = re.split(r'(?<=[.!?])\s+', text)
            text = ' '.join(sents[:2])

        return text.strip()


    def _add(self, user: str, assistant: str):
        self.history.append({'role': 'user', 'content': user})
        self.history.append({'role': 'assistant', 'content': assistant})

    def clear_history(self):
        self.history.clear()

    # ── Tool schemas ──────────────────────────────────────────────────────────
    def _schemas(self) -> list:
        return [
            {'type': 'function', 'function': {
                'name': 'open_url',
                'description': (
                    'Open any URL in the browser. Use for: websites, YouTube search, '
                    'Google search, specific pages. '
                    'For YouTube: url=https://youtube.com/results?search_query=X'),
                'parameters': {
                    'type': 'object',
                    'properties': {'url': {'type': 'string',
                                          'description': 'Full URL with https://'}},
                    'required': ['url']
                }
            }},
            {'type': 'function', 'function': {
                'name': 'play_youtube',
                'description': (
                    'Search YouTube and immediately play the first result using mpv. '
                    'Use this when user says "play X", "play a song", "play any video". '
                    'This ACTUALLY PLAYS the video, unlike open_url which just opens a page.'),
                'parameters': {
                    'type': 'object',
                    'properties': {'query': {'type': 'string',
                                            'description': 'What to search and play, e.g. "tmkoc ep 231"'}},
                    'required': ['query']
                }
            }},
            {'type': 'function', 'function': {
                'name': 'run_command',
                'description': 'Run any bash command on Ubuntu. For file ops, git, system tasks, installing things.',
                'parameters': {
                    'type': 'object',
                    'properties': {'command': {'type': 'string',
                                              'description': 'Bash command to run'}},
                    'required': ['command']
                }
            }},
            {'type': 'function', 'function': {
                'name': 'get_system_info',
                'description': 'Get CPU, RAM, disk, GPU usage and temperature. Speaks as natural sentences.',
                'parameters': {'type': 'object', 'properties': {}, 'required': []}
            }},
            {'type': 'function', 'function': {
                'name': 'open_app',
                'description': 'Open a desktop application.',
                'parameters': {
                    'type': 'object',
                    'properties': {'app': {'type': 'string',
                                          'description': 'App name e.g. gnome-terminal, code, firefox, spotify'}},
                    'required': ['app']
                }
            }},
            {'type': 'function', 'function': {
                'name': 'create_file',
                'description': 'Create a file with optional content.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'path': {'type': 'string', 'description': 'File path e.g. ~/test.py'},
                        'content': {'type': 'string', 'default': '',
                                   'description': 'File content'}
                    },
                    'required': ['path']
                }
            }},
            {'type': 'function', 'function': {
                'name': 'read_screen',
                'description': (
                    'Take screenshot then read all text using OCR. '
                    'Use for: "what is on my screen", "read this error", '
                    '"what does this say", "look at this file I have open".'),
                'parameters': {'type': 'object', 'properties': {}, 'required': []}
            }},
            {'type': 'function', 'function': {
                'name': 'keyboard_shortcut',
                'description': (
                    'Press keyboard shortcut. '
                    'ctrl+w=close tab, alt+f4=close window, ctrl+t=new tab, '
                    'ctrl+l=address bar, ctrl+r=reload, ctrl+z=undo.'),
                'parameters': {
                    'type': 'object',
                    'properties': {'keys': {'type': 'string',
                                           'description': 'e.g. ctrl+w, alt+f4, ctrl+t'}},
                    'required': ['keys']
                }
            }},
            {'type': 'function', 'function': {
                'name': 'type_text',
                'description': 'Type text into the currently focused window or app.',
                'parameters': {
                    'type': 'object',
                    'properties': {'text': {'type': 'string'}},
                    'required': ['text']
                }
            }},
            {'type': 'function', 'function': {
                'name': 'click_play',
                'description': (
                    'Click the first video on the current YouTube page to play it. '
                    'Use ONLY after open_url opened YouTube search results. '
                    'When user says "play it", "play one", "click play".'),
                'parameters': {'type': 'object', 'properties': {}, 'required': []}
            }},
            {'type': 'function', 'function': {
                'name': 'vscode_file',
                'description': (
                    'Read the currently open file in VS Code. '
                    'Use when: "look at this file", "read my code", '
                    '"what file is open", "what am I working on".'),
                'parameters': {'type': 'object', 'properties': {}, 'required': []}
            }},
            {'type': 'function', 'function': {
                'name': 'get_active_window',
                'description': 'Get the title of the currently focused window or app.',
                'parameters': {'type': 'object', 'properties': {}, 'required': []}
            }},
        ]

    @property
    def user_name(self): return self._user
    @property
    def assistant_name(self): return self._name
