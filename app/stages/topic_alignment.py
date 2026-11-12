"""Generic relevance checks for keeping generated copy tied to its input problem."""

import re


_COMMON_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by",
    "can", "could", "did", "do", "does", "face", "for", "from", "get",
    "gets", "had", "has", "have", "how", "in", "into", "is", "it", "its",
    "may", "might", "more", "of", "on", "or", "our", "out", "over",
    "people", "problem", "process", "recent", "result", "same", "should",
    "some", "such", "team", "that", "the", "their", "them", "there",
    "these", "they", "this", "those", "through", "to", "under", "up",
    "use", "users", "using", "was", "were", "when", "where", "which",
    "while", "who", "will", "with", "without", "would", "your",
}


def _terms(text: str) -> set[str]:
    terms = set(re.findall(r"[a-z0-9]+", (text or "").casefold()))
    return {term for term in terms if len(term) > 2 and term not in _COMMON_WORDS}


def matches_problem_topic(problem: str, candidate: str) -> bool:
    """Check for meaningful lexical overlap without assuming any industry vocabulary."""
    anchors = _terms(problem)
    if not anchors:
        return True
    candidate_terms = _terms(candidate)
    # Keep the guard permissive so the drafting agent can paraphrase the problem.
    minimum = 1
    return len(anchors & candidate_terms) >= minimum
