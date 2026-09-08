"""Tests for broadcasting.validation dataset-hygiene helpers."""

from broadcasting.validation import dedupe_by_job, find_duplicate_jobs, group_by_cohort


def _run(job_id=None, backend="ibm_kingston", shots=4096, filename="r.json"):
    return {"job_id": job_id, "backend": backend, "shots": shots, "filename": filename}


class TestFindDuplicateJobs:
    def test_no_duplicates(self):
        runs = [_run(job_id="a"), _run(job_id="b")]
        assert find_duplicate_jobs(runs) == {}

    def test_detects_duplicate(self):
        runs = [
            _run(job_id="dup", filename="one.json"),
            _run(job_id="dup", filename="two.json"),
            _run(job_id="unique", filename="three.json"),
        ]
        dupes = find_duplicate_jobs(runs)
        assert set(dupes.keys()) == {"dup"}
        assert set(dupes["dup"]) == {"one.json", "two.json"}

    def test_missing_job_id_ignored(self):
        runs = [_run(job_id=None), _run(job_id=None)]
        assert find_duplicate_jobs(runs) == {}


class TestGroupByCohort:
    def test_groups_by_backend_and_shots(self):
        runs = [
            _run(backend="ibm_kingston", shots=4096),
            _run(backend="ibm_kingston", shots=4096),
            _run(backend="ibm_marrakesh", shots=8192),
        ]
        groups = group_by_cohort(runs)
        assert len(groups) == 2
        assert len(groups[("ibm_kingston", 4096)]) == 2
        assert len(groups[("ibm_marrakesh", 8192)]) == 1


class TestDedupeByJob:
    def test_keeps_first_drops_rest(self):
        runs = [
            _run(job_id="dup", filename="first.json"),
            _run(job_id="dup", filename="second.json"),
        ]
        kept = dedupe_by_job(runs)
        assert len(kept) == 1
        assert kept[0]["filename"] == "first.json"

    def test_runs_without_job_id_all_kept(self):
        runs = [_run(job_id=None), _run(job_id=None)]
        assert len(dedupe_by_job(runs)) == 2
