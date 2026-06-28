"""Benchmark engine — runs small self-contained tasks against the current model.

Each task is scored 0–10. Overall score is the weighted average scaled to 100.
No external network calls required — only model inference via Ollama/configured provider.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.benchmark")


@dataclass
class TaskResult:
    name: str
    score: int          # 0–10
    max_score: int = 10
    passed: bool = False
    details: str = ""
    latency_ms: int = 0


@dataclass
class BenchmarkResult:
    task_results: list[TaskResult] = field(default_factory=list)
    overall_score: int = 0         # 0–100
    model: str = ""
    provider: str = ""
    best_for: list[str] = field(default_factory=list)
    weak_for: list[str] = field(default_factory=list)
    suggestion: str = ""
    duration_s: float = 0.0


class BenchmarkRunner:
    """Runs benchmark tasks and produces a BenchmarkResult."""

    TASKS = [
        {
            "name": "simple_edit",
            "weight": 2,
            "prompt": (
                "Fix the bug in this Python function and return ONLY the corrected code, "
                "no explanation:\n\n"
                "def add(a, b):\n    return a - b\n"
            ),
            "check": lambda r: "a + b" in r or "return a+b" in r.replace(" ", ""),
            "desc": "Small surgical edit (fix a bug)",
        },
        {
            "name": "docstring",
            "weight": 1,
            "prompt": (
                "Write a one-line Python docstring for this function. "
                "Return ONLY the docstring text (no quotes, no def line):\n\n"
                "def calculate_area(width, height):\n    return width * height\n"
            ),
            "check": lambda r: len(r.strip()) > 5 and len(r.strip()) < 200 and "\n\n" not in r.strip(),
            "desc": "Docstring generation",
        },
        {
            "name": "bug_fix",
            "weight": 2,
            "prompt": (
                "This Python function has a bug. Return ONLY the fixed function, no explanation:\n\n"
                "def find_max(numbers):\n"
                "    max_val = 0\n"
                "    for n in numbers:\n"
                "        if n > max_val:\n"
                "            max_val = n\n"
                "    return max_val\n"
                "\nHint: fails for all-negative lists."
            ),
            "check": lambda r: (
                "numbers[0]" in r or
                "float('-inf')" in r or
                "max(" in r or
                "= None" in r or
                "is None" in r
            ),
            "desc": "Bug fix (edge case)",
        },
        {
            "name": "test_generation",
            "weight": 2,
            "prompt": (
                "Write a single pytest test function for this code. "
                "Return ONLY the test function, no imports, no explanation:\n\n"
                "def multiply(a, b):\n    return a * b\n"
            ),
            "check": lambda r: "def test_" in r and "assert" in r and "multiply" in r,
            "desc": "Test generation",
        },
        {
            "name": "summarize",
            "weight": 1,
            "prompt": (
                "Summarize what this Python module does in one sentence (max 20 words):\n\n"
                "import os\nimport json\n\n"
                "def load_config(path):\n"
                "    with open(path) as f:\n"
                "        return json.load(f)\n\n"
                "def save_config(path, data):\n"
                "    with open(path, 'w') as f:\n"
                "        json.dump(data, f)\n"
            ),
            "check": lambda r: 3 < len(r.split()) <= 25,
            "desc": "Code summarization",
        },
        {
            "name": "refactor",
            "weight": 2,
            "prompt": (
                "Refactor this Python code to use a list comprehension. "
                "Return ONLY the refactored code:\n\n"
                "result = []\n"
                "for i in range(10):\n"
                "    if i % 2 == 0:\n"
                "        result.append(i * i)\n"
            ),
            "check": lambda r: "[" in r and "for" in r and "if" in r and "result" in r.lower(),
            "desc": "List comprehension refactor",
        },
    ]

    def __init__(self, cfg: AppConfig, on_progress=None) -> None:
        self._cfg = cfg
        self._on_progress = on_progress  # callback(task_name, index, total)

    def run(self) -> BenchmarkResult:
        start = time.monotonic()
        results = BenchmarkResult(
            model=self._cfg.ollama_model,
            provider=self._cfg.provider,
        )

        total = len(self.TASKS)
        for idx, task_def in enumerate(self.TASKS):
            if self._on_progress:
                self._on_progress(task_def["name"], idx, total)
            task_result = self._run_task(task_def)
            results.task_results.append(task_result)

        results.duration_s = time.monotonic() - start
        results.overall_score = self._compute_score(results.task_results)
        results.best_for = [
            t.name for t in results.task_results if t.score >= 7
        ]
        results.weak_for = [
            t.name for t in results.task_results if t.score < 5
        ]
        results.suggestion = self._make_suggestion(results)
        return results

    # ── internals ─────────────────────────────────────────────────────────

    def _run_task(self, task_def: dict) -> TaskResult:
        name = task_def["name"]
        t0 = time.monotonic()
        try:
            response = self._query_model(task_def["prompt"])
            latency = int((time.monotonic() - t0) * 1000)
            passed = task_def["check"](response)
            score = 10 if passed else 3  # partial credit for responding at all
            # Bonus: short response (no padding) gets +1 if passed
            if passed and len(response.strip()) < 400:
                score = min(10, score)
            return TaskResult(
                name=name,
                score=score,
                passed=passed,
                details=response.strip()[:120],
                latency_ms=latency,
            )
        except Exception as exc:
            latency = int((time.monotonic() - t0) * 1000)
            _log.warning("Benchmark task '%s' failed: %s", name, exc)
            return TaskResult(name=name, score=0, passed=False,
                              details=str(exc)[:80], latency_ms=latency)

    def _query_model(self, prompt: str) -> str:
        """Send prompt to current provider and return text response."""
        import httpx
        provider = self._cfg.provider

        if provider in ("ollama", "meta"):
            r = httpx.post(
                f"{self._cfg.ollama_url}/api/generate",
                json={
                    "model": self._cfg.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 300},
                },
                timeout=60.0,
            )
            r.raise_for_status()
            return r.json().get("response", "")

        if provider == "anthropic":
            return self._query_anthropic(prompt)

        if provider == "openai":
            return self._query_openai(prompt)

        if provider == "groq":
            return self._query_groq(prompt)

        if provider == "gemini":
            return self._query_gemini(prompt)

        raise NotImplementedError(
            f"Benchmark does not support provider '{provider}'. "
            "Supported: ollama, anthropic, openai, groq, gemini."
        )

    def _chat_model(self) -> str:
        """Return the best available model name for chat benchmarking."""
        return self._cfg.chat_model or self._cfg.ollama_model or "default"

    def _query_anthropic(self, prompt: str) -> str:
        """POST to Anthropic Messages API and return the text reply."""
        import httpx

        from app.core.secret_store import get_api_key
        api_key = get_api_key("anthropic")
        if not api_key:
            raise RuntimeError(
                "No Anthropic API key stored. Use /setup or /provider anthropic."
            )
        model = self._chat_model()
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.json()
        content = data.get("content", [])
        return content[0].get("text", "") if content else ""

    def _query_openai(self, prompt: str) -> str:
        """POST to OpenAI Chat Completions API and return the text reply."""
        import httpx

        from app.core.secret_store import get_api_key
        api_key = get_api_key("openai")
        if not api_key:
            raise RuntimeError(
                "No OpenAI API key stored. Use /setup or /provider openai."
            )
        model = self._chat_model()
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 400,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60.0,
        )
        r.raise_for_status()
        choices = r.json().get("choices", [])
        return choices[0]["message"]["content"] if choices else ""

    def _query_groq(self, prompt: str) -> str:
        """POST to Groq's OpenAI-compatible API and return the text reply."""
        import httpx

        from app.core.secret_store import get_api_key
        api_key = get_api_key("groq")
        if not api_key:
            raise RuntimeError(
                "No Groq API key stored. Use /setup or /provider groq."
            )
        model = self._chat_model()
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 400,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60.0,
        )
        r.raise_for_status()
        choices = r.json().get("choices", [])
        return choices[0]["message"]["content"] if choices else ""

    def _query_gemini(self, prompt: str) -> str:
        """POST to Gemini generateContent API and return the text reply."""
        import httpx

        from app.core.secret_store import get_api_key
        api_key = get_api_key("gemini")
        if not api_key:
            raise RuntimeError(
                "No Gemini API key stored. Use /setup or /provider gemini."
            )
        model = self._chat_model()
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 400, "temperature": 0.1},
            },
            timeout=60.0,
        )
        r.raise_for_status()
        candidates = r.json().get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return parts[0].get("text", "") if parts else ""

    def _compute_score(self, results: list[TaskResult]) -> int:
        task_map = {t["name"]: t["weight"] for t in self.TASKS}
        total_weight = sum(task_map.values())
        weighted_sum = sum(
            r.score * task_map.get(r.name, 1) for r in results
        )
        max_possible = total_weight * 10
        return int((weighted_sum / max_possible) * 100)

    def _make_suggestion(self, result: BenchmarkResult) -> str:
        score = result.overall_score
        if score >= 85:
            return f"Excellent! {result.model} is production-ready for all coding tasks."
        if score >= 70:
            return f"Good. {result.model} handles most tasks well. Use /route quality for complex refactors."
        if score >= 50:
            return (
                f"{result.model} is adequate for simple edits. "
                "Consider /route free-only to route complex tasks to Gemini."
            )
        return (
            f"{result.model} struggles. Try /setup local to install a larger model, "
            "or /route free-only to use Gemini for free."
        )
