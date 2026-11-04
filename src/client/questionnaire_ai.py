"""
questionnaire_ai.py — AI-powered questionnaire answerer with local caching.

Resolution order for each question:
  1. qa_cache.json  (exact text match, persisted across runs)
  2. common_qa      (profile-derived patterns + user-configured pairs)
  3. Batched AI call (all uncached questions in one API round-trip)
  4. Static fallback (heuristics, no network)

Set  questionnaire.skip_ai = true  in config.json to skip AI calls entirely
while still getting cache + common_qa matches.

Cache file: qa_cache.json  (project root, gitignored)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_CACHE_PATH = Path("qa_cache.json")


class QuestionnaireAI:
    """
    Answers Naukri questionnaire dicts.

    Usage:
        qa = QuestionnaireAI(config_manager)
        answers = qa.answer(questionnaire_list, job)
        # pass `answers` to handle_static_questionnaire_and_apply
    """

    def __init__(self, config_manager, cache_path: Path = _CACHE_PATH) -> None:
        self._cfg        = config_manager
        self._cache_path = Path(cache_path)
        self._cache: dict[str, Any] = self._load_cache()
        self._profile    = config_manager.config.get("profile", {})
        self._common_qa  = self._build_common_qa()

    # ── Public API ─────────────────────────────────────────────────────────────

    def answer(self, questionnaire: list[dict], job=None) -> dict:
        """
        Returns {questionId: answer} for the full questionnaire.

        answer values follow the same contract as the existing
        build_smart_answers() helper:
          - text-box question  →  str
          - option question    →  list[str]  (single-element for most)
        """
        # Pass 1 — resolve from cache / common_qa
        resolved: dict[str, Any] = {}
        pending: list[dict]      = []

        for q in questionnaire:
            qid     = q["questionId"]
            qtext   = (q.get("questionName") or "").strip()
            options = q.get("answerOption") or {}
            cached  = self._lookup(qtext, options)
            if cached is not None:
                resolved[qid] = cached
            else:
                pending.append(q)

        # Pass 2 — batch AI call for all unknowns (one round-trip)
        if pending and self._cfg.get_ai_key():
            ai_answers = self._ai_batch(pending, job)
            for q in pending:
                qid   = q["questionId"]
                qtext = (q.get("questionName") or "").strip()
                ans   = ai_answers.get(qid)
                if ans is not None:
                    resolved[qid] = ans
                    self._cache[self._norm(qtext)] = ans
            if any(ai_answers.values()):
                self._save_cache()

        # Pass 3 — static fallback for anything still unresolved
        for q in questionnaire:
            qid = q["questionId"]
            if qid not in resolved:
                resolved[qid] = self._static(q)

        return resolved

    # ── Cache ──────────────────────────────────────────────────────────────────

    def _load_cache(self) -> dict:
        if self._cache_path.exists():
            try:
                with open(self._cache_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_cache(self) -> None:
        try:
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except Exception:
            pass

    # ── Lookup (cache + common_qa) ─────────────────────────────────────────────

    @staticmethod
    def _norm(text: str) -> str:
        """Lowercase, strip punctuation — used as cache key."""
        return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()

    def _lookup(self, text: str, options: dict) -> Any | None:
        key = self._norm(text)

        # Cache hit
        if key in self._cache:
            cached = self._cache[key]
            if options and isinstance(cached, list):
                if all(k in options for k in cached):
                    return cached
                # cached keys no longer valid (job has different options) — skip
            elif not options:
                return cached

        # common_qa fuzzy match (is the pattern a substring of the question or vice-versa)
        for entry in self._common_qa:
            pattern = self._norm(entry["question"])
            if pattern in key or key in pattern:
                raw = entry["answer"]
                if options:
                    ans = self._match_option(raw, options)
                    if ans:
                        result = [ans]
                        self._cache[key] = result
                        self._save_cache()
                        return result
                else:
                    self._cache[key] = raw
                    self._save_cache()
                    return raw

        return None

    @staticmethod
    def _match_option(value: str, options: dict) -> str | None:
        """Find the option key whose label best matches value."""
        value_lower = value.lower()
        for ok, ov in options.items():
            if value_lower in ov.lower() or ov.lower() in value_lower:
                return ok
        return None

    # ── Batched AI call ────────────────────────────────────────────────────────

    def _ai_batch(self, questions: list[dict], job=None) -> dict:
        """
        Send all unanswered questions in one API request.
        Returns {questionId: answer}.
        """
        p = self._profile

        profile_line = (
            f"{p.get('role_focus','backend')} developer, "
            f"{p.get('experience_years',2)} yrs exp, "
            f"stack: {', '.join(p.get('tech_stack',[])[:6])}, "
            f"notice: {p.get('notice_days',30)} days, "
            f"CTC: {p.get('current_ctc','5')} -> {p.get('expected_ctc','7')} LPA"
        )
        job_line = ""
        if job:
            job_line = (
                f"\nJob: {getattr(job,'title','')} "
                f"at {getattr(job,'company','')}"
            )

        # Build the question block
        q_lines: list[str] = []
        for i, q in enumerate(questions, 1):
            qtext   = (q.get("questionName") or "").strip()
            qtype   = (q.get("questionType") or "").lower()
            options = q.get("answerOption") or {}

            line = f"Q{i} ({'text' if qtype == 'text box' else 'choice'}): \"{qtext}\""
            if options:
                opts = "  |  ".join(f"{k}: {v}" for k, v in list(options.items())[:6])
                line += f"\n   Options: {opts}"
            q_lines.append(line)

        q_block = "\n".join(q_lines)

        reply_format = "\n".join(f"Q{i}: <answer>" for i in range(1, len(questions) + 1))

        prompt = (
            f"You are filling in a job application form for a candidate.\n"
            f"Profile: {profile_line}.{job_line}\n\n"
            f"Answer each question with ONE short value.\n"
            f"For choice questions: reply with the option KEY (e.g. \"option_1\").\n"
            f"For text questions: reply with a plain short value (number, Yes, No, etc.).\n\n"
            f"{q_block}\n\n"
            f"Reply in EXACTLY this format, one line per question:\n"
            f"{reply_format}"
        )

        try:
            from curl_cffi import requests as _r
            payload = {
                "model":       self._cfg.config["ai"].get("model", "gpt-4o-mini"),
                "messages":    [{"role": "user", "content": prompt}],
                "max_tokens":  len(questions) * 30 + 50,
                "temperature": 0,
            }
            resp = _r.post(
                self._cfg.get_ai_url(),
                headers=self._cfg.get_ai_headers(),
                json=payload,
                timeout=20,
            )
            if not resp.ok:
                return {}
            raw = resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            return {}

        return self._parse_ai_reply(raw, questions)

    def _parse_ai_reply(self, raw: str, questions: list[dict]) -> dict:
        """
        Parse the AI's Q1/Q2/… reply back into {questionId: answer}.
        """
        answers: dict = {}
        for i, q in enumerate(questions, 1):
            qid     = q["questionId"]
            options = q.get("answerOption") or {}

            # Look for "Q{i}: <value>" in the reply
            match = re.search(rf"Q{i}\s*:\s*(.+)", raw, re.IGNORECASE)
            if not match:
                continue

            raw_val = match.group(1).strip().strip('"').strip("'")

            if options:
                # Try exact key match first
                if raw_val in options:
                    answers[qid] = [raw_val]
                    continue
                # Try label match
                ok = self._match_option(raw_val, options)
                if ok:
                    answers[qid] = [ok]
                    continue
                # Fallback to first option
                answers[qid] = [list(options.keys())[0]]
            else:
                answers[qid] = raw_val

        return answers

    # ── Static fallback ────────────────────────────────────────────────────────

    def _static(self, q: dict) -> Any:
        """Heuristic answers when neither cache nor AI is available."""
        p       = self._profile
        qtext   = (q.get("questionName") or "").lower()
        qtype   = (q.get("questionType") or "").lower()
        options = q.get("answerOption") or {}
        exp     = str(p.get("experience_years", 2))

        if qtype == "text box":
            if "current ctc" in qtext:  return p.get("current_ctc", "5")
            if "expected ctc" in qtext: return p.get("expected_ctc", "7")
            if "notice" in qtext:       return str(p.get("notice_days", 30))
            if "experience" in qtext:   return exp
            return "1"

        if options:
            # Prefer Yes-like options; fall back to first
            for k, v in options.items():
                if "yes" in v.lower():
                    return [k]
            return [list(options.keys())[0]]

        return "1"

    # ── Common Q&A seed ────────────────────────────────────────────────────────

    def _build_common_qa(self) -> list[dict]:
        """
        15 profile-derived Q&A pairs + any user-configured ones from config.json.
        These are matched before an AI call is made, saving tokens.

        Extend via config.json:
          "questionnaire": {
            "common_qa": [
              {"question": "Are you comfortable working in shifts?", "answer": "No"}
            ]
          }
        """
        p = self._profile
        exp     = p.get("experience_years", 2)
        notice  = p.get("notice_days", 30)
        cur_ctc = str(p.get("current_ctc", "5"))
        exp_ctc = str(p.get("expected_ctc", "7"))
        stack   = p.get("tech_stack", [])
        remote  = p.get("apply_remote", True)

        # Map notice_days to the most common Naukri dropdown label
        if notice == 0:
            notice_label = "Immediate"
        elif notice <= 15:
            notice_label = "15 days or less"
        elif notice <= 30:
            notice_label = "1 month"
        elif notice <= 60:
            notice_label = "2 months"
        else:
            notice_label = "3 months or more"

        defaults: list[dict] = [
            # CTC / compensation
            {"question": "what is your current ctc",             "answer": cur_ctc},
            {"question": "current ctc",                          "answer": cur_ctc},
            {"question": "what is your expected ctc",            "answer": exp_ctc},
            {"question": "expected ctc",                         "answer": exp_ctc},
            # Notice
            {"question": "what is your notice period",           "answer": notice_label},
            {"question": "notice period",                        "answer": notice_label},
            {"question": "can you join immediately",             "answer": "Yes" if notice == 0 else "No"},
            # Experience
            {"question": "total years of experience",            "answer": str(exp)},
            {"question": "how many years of experience",         "answer": str(exp)},
            {"question": "are you a fresher",                    "answer": "No" if exp > 0 else "Yes"},
            # Logistics
            {"question": "are you willing to relocate",          "answer": "Yes"},
            {"question": "are you willing to work from office",  "answer": "Yes"},
            {"question": "are you open to work from home",       "answer": "Yes" if remote else "No"},
            {"question": "are you comfortable with night shifts", "answer": "No"},
            {"question": "are you comfortable with field work",  "answer": "No"},
            # Background
            {"question": "are you an indian national",           "answer": "Yes"},
            {"question": "are you currently employed",           "answer": "Yes"},
            {"question": "have you worked in a startup",         "answer": "Yes"},
            {"question": "are you open to contract roles",       "answer": "No"},
            {"question": "are you open to freelance",            "answer": "No"},
        ]

        # Inject tech-stack specific entries so "do you know Node.js?" type questions
        # are resolved from cache without an AI call.
        for tech in stack[:8]:
            tl = tech.lower()
            defaults += [
                {"question": f"do you have experience with {tl}",   "answer": "Yes"},
                {"question": f"experience in {tl}",                 "answer": str(exp)},
                {"question": f"years of experience in {tl}",        "answer": str(exp)},
                {"question": f"how many years of {tl} experience",  "answer": str(exp)},
            ]

        # Merge user-configured pairs from config.json (they come last so they
        # match first in the lookup loop, effectively overriding defaults).
        user_qa = self._cfg.config.get("questionnaire", {}).get("common_qa", [])
        return user_qa + defaults
