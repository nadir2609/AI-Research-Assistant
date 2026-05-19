## What this PR changes

This PR implements the concurrency orchestration layer for the Async Research Assistant project. It adds asynchronous parallel source fetching using `asyncio.gather` for Wikipedia, arXiv, and web search sources. The implementation also includes per-source timeout handling and graceful degradation so that one failed source does not terminate the entire research pipeline.

## Why

This change implements the required concurrency layer for Topic 4: Async Research Assistant.

Closes #6

## How I tested it

- [ ] `pytest` passes locally
- [x] `pytest tests/test_ai_smoke.py` (provided smoke tests) passes
- [ ] Coverage stayed at or above the threshold (run `pytest --cov`)
- [ ] If touching `Dockerfile` or `requirements.txt`: `docker build .` succeeds

Manual testing steps:

```bash
python demo_ai.py --offline
python -m src.cli ask "What is artificial intelligence?"