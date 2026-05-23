# Contribution Statement

**Team:** Matrix
**Topic:** Topic 4: AI-research assistant
**Repository:** _[https://github.com/nadir2609/AI-Research-Assistant](https://github.com/nadir2609/AI-Research-Assistant)_
**Final tag:** `v1.0-final`
**Submission date:** 2026-05-24

---

## How to fill this in

This is the single piece of evidence we use to assess **individual contribution** within the team. Rules:

1. Every member writes their own three subsections (Owned, Co-owned, Reviewed).
2. **Be specific.** "Worked on the backend" is not acceptable; "implemented `src/services/ai_service.py` and `src/concurrency/pipeline.py`, owned PRs #4, #7, #11" is.
3. The committed-percentages must add to 100% and approximately match `git shortlog -sn` on the `main` branch.
4. All three members must sign at the bottom. Unsigned submissions are returned ungraded.

If one member contributed less than 10% without a documented reason (illness, emergency), the team loses 5 points automatically per the rubric.

---

## Member A — Narmina IbrahimovaName (`@nnrmina)

**Owned (sole author of these files / PRs):**
- `src/concurrency/orchestrator.py`
- `src/static/index.html`
- `src/logging.py`
- `tests/test_orchestrator.py`
- PRs: _[15,14,9]_

**Reviewed (PRs reviewed and merged):**
- PRs: _[11,3,7]_

**Approximate share of commits:** 30%

## Member B — Nadir Askerov(`@nadir2609)

**Owned:**
- `src/core/researcher.py`
- `src/services/external_policy.py`
- `src/config.py`
- `src/cli.py`
- `src/api.py`
- `tests/test_external_policy.py`
- `tests/test_config.py`
- `tests/conftest.py`
- ``
- PRs: _[4,7,11]_

**Co-owned :**
- `Dockerfile,docker-compose.yml,docker/*` (with Member C)

**Reviewed (PRs reviewed and merged):**
- PRs: _[8,3,9]_

**Approximate share of commits:** 30%

---

## Member C — Avaz Huseynov (`@evez12`)

**Owned:**
- `src/storage/*`
- `src/services/research_service.py`
- `src/validation.py`
- `tests/test_storage_repository.py`
- `tests/test_validation.py`
- `tests/test_research_service_cache.py`
- `tests/test_input_validation.py`
- `tests/test_source_cahce.py`
- PRs: _[3,5,6,8]_

**Co-owned :**
- `Dockerfile,docker-compose.yml,docker/*` (with Member B)

**Reviewed (PRs reviewed and merged):**
- PRs: _[10,7,1,]_

**Approximate share of commits:** 40%

---

## AI tool disclosure (also in §10 of the report)

We used AI coding assistants as follows. Each item lists the module, the assistant, and what the team did with the output.

| Module / file | Assistant     | What we did with it                                                                                                                                                                                     |
|---------------|---------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `src/*`       | Cursor        | Drafted code snippets, helper functions, and refactor suggestions; the team reviewed, adapted the output to our architecture, fixed edge cases, and added unit tests before committing.                 |
| `tests/*`     | GitHub Copilot | Generated test skeletons and example assertions; the team reviewed and corrected expectations, added fixtures, and kept or rewrote tests as needed.                                                     |
| `docker/`     | Claude        | it help us to write almost each docker components)). Drafted Dockerfiles, entrypoint scripts, and compose configs; the team reviewed, hardened, and tested all components in local and CI environments. |

We affirm that we **can defend every line of code** in this repository during the oral defense. "The AI wrote it" is not an answer we will use.

---

## Signatures

By signing below, we affirm that:
- The contributions described above are accurate.
- The commit percentages reflect actual work, not artificially split commits.
- Every line of code in the repository can be defended by at least one team member.
- AI assistant usage has been disclosed as described above.

| Member             | Signature | Date       |
|--------------------|---|------------|
| Narmina Ibrahimova | __________________________ | 23.05.2026 |
| Nadir Askerov      | __________________________ | 23.05.2026|
| Avaz Huseynov      | __________________________ | 23.05.2026 |
