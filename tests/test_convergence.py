"""Recorded errors, numerical convergence and resumable experiment records."""
from dataclasses import replace
import json
import re

import numpy as np
import pytest

from broadcasting import convergence as conv
from broadcasting.protocol import BroadcastResult


def test_seed_zero_retains_actual_grid_parameters_and_printed_errors(tmp_path):
    study = conv.load_convergence(results_dir=tmp_path, seed_zero_path=conv.SEED_ZERO_PATH)
    assert study.config.M == 1 and study.config.N == 2
    assert study.config.alpha == 1 / np.sqrt(2)
    assert study.config.seed == 0 and study.config.outcomes_list == [0]
    assert study.config.thetas == [0.0] and study.config.use_qec
    assert study.config.p_list == np.linspace(0, 1, 21).tolist()
    assert study.sample_counts == [50, 100, 200, 500, 1000, 2000, 5000, 10000, 50000, 100000]
    rows = re.findall(r"n_samples=\s*(\d+)\s+per-receiver error=\[([^\]]+)\]", study.seed_zero["source"]["printed_output"])
    assert study.seed_zero["errors_per_receiver"] == [[float(x) for x in v.split()] for _, v in rows]
    assert study.seed_zero["errors_per_receiver"][-1] == [0.00127751, 0.00120541]
    assert study.repetitions == []


def test_error_uses_per_receiver_integrated_absolute_difference():
    p = [0, 0.2, 1]
    exact = np.zeros((3, 2))
    sampled = [[-0.2, 0.4], [0.4, -0.5], [-0.6, 0.1]]
    assert conv.fidelity_error(sampled, exact, p) == pytest.approx([0.46, 0.33])
    with pytest.raises(ValueError, match="share one increasing"):
        conv.fidelity_error(sampled, exact, [0, 1, 0.5])
    with pytest.raises(ValueError, match="share one increasing"):
        conv.fidelity_error(sampled[:-1], exact, p)


@pytest.mark.parametrize("probabilities", [[0, np.inf], [[0], [1]], [0, np.nan], 1])
def test_error_rejects_nonfinite_or_nonvector_probability_grid(probabilities):
    with pytest.raises(ValueError, match="share one increasing"):
        conv.fidelity_error([[0.1], [0.2]], [[0], [0]], probabilities)


def _fake_backends(monkeypatch, failures=None):
    seen = []
    class Exact:
        def run(self, config):
            seen.append(("exact", config.seed, config.n_samples))
            return BroadcastResult(np.full((len(config.p_list), config.N), 0.5).tolist(), metadata={"mode": "exact"})
    class Sampling:
        def run(self, config):
            seen.append(("sample", config.seed, config.n_samples))
            if failures and (config.seed, config.n_samples) in failures:
                raise RuntimeError("interrupted")
            return BroadcastResult(np.full((len(config.p_list), config.N), 0.5 + config.seed / config.n_samples).tolist(),
                                   metadata={"mode": "sampling", "seed": config.seed,
                                             "n_samples": config.n_samples, "software": {"test": True}})
    monkeypatch.setattr(conv, "ExactBackend", Exact)
    monkeypatch.setattr(conv, "SamplingBackend", Sampling)
    return seen


def test_collection_persists_effective_seeds_counts_reference_and_resumes(monkeypatch, tmp_path):
    seen = _fake_backends(monkeypatch)
    study = conv.load_convergence(results_dir=tmp_path, seed_zero_path=conv.SEED_ZERO_PATH)
    identity = "two_repeats"
    conv.collect_convergence_repeats(study, seeds=[1, 2], sample_counts=[50, 100], study_id=identity, results_dir=tmp_path)
    assert seen == [("exact", 0, None)] + [("sample", seed, count) for seed in [1, 2] for count in [50, 100]]
    loaded = conv.load_convergence(results_dir=tmp_path, seed_zero_path=conv.SEED_ZERO_PATH)
    assert len(loaded.repetitions) == 2
    for repetition in loaded.repetitions:
        assert repetition["complete"]
        for point in repetition["points"]:
            assert sum(point["errors_per_receiver"]) == pytest.approx(2 * repetition["seed"] / point["n_samples"])
            raw = json.loads(open(point["path"]).read())
            assert raw["metadata"]["software"] == {"test": True}
    checksums = {p: p.read_bytes() for p in tmp_path.glob("*.json")}
    conv.collect_convergence_repeats(loaded, seeds=[1, 2], sample_counts=[50, 100], study_id=identity, results_dir=tmp_path)
    assert len(seen) == 5
    assert checksums == {p: p.read_bytes() for p in tmp_path.glob("*.json")}
    with pytest.raises(ValueError, match="Study settings changed"):
        conv.collect_convergence_repeats(loaded, seeds=[1, 2], sample_counts=[50], study_id=identity, results_dir=tmp_path)
    with pytest.raises(ValueError, match="previously used"):
        conv.collect_convergence_repeats(loaded, seeds=[1, 2], sample_counts=[50], study_id="duplicate", results_dir=tmp_path)


def test_interruption_retains_finished_points_and_resumes(monkeypatch, tmp_path):
    failures = {(1, 100)}
    seen = _fake_backends(monkeypatch, failures)
    study = conv.load_convergence(results_dir=tmp_path, seed_zero_path=conv.SEED_ZERO_PATH)
    with pytest.raises(RuntimeError, match="interrupted"):
        conv.collect_convergence_repeats(study, repeats=1, seeds=[1], sample_counts=[50, 100], study_id="resume", results_dir=tmp_path)
    loaded = conv.load_convergence(results_dir=tmp_path, seed_zero_path=conv.SEED_ZERO_PATH)
    assert len(loaded.repetitions[0]["points"]) == 1
    assert not loaded.repetitions[0]["complete"]
    failures.clear()
    conv.collect_convergence_repeats(loaded, repeats=1, seeds=[1], sample_counts=[50, 100], study_id="resume", results_dir=tmp_path)
    assert seen.count(("exact", 0, None)) == 1
    assert seen.count(("sample", 1, 50)) == 1
    assert seen.count(("sample", 1, 100)) == 2


def test_sampled_result_is_independent_of_reference_files_and_detects_tampering(monkeypatch, tmp_path):
    import shutil
    _fake_backends(monkeypatch)
    source = tmp_path / "source"
    study = conv.load_convergence(results_dir=source, seed_zero_path=conv.SEED_ZERO_PATH)
    conv.collect_convergence_repeats(study, repeats=1, sample_counts=[50],
                                     study_id="portable", results_dir=source)
    copied_dir = tmp_path / "copied"
    copied_dir.mkdir()
    copied = copied_dir / "one_result.json"
    shutil.copyfile(source / "run_portable_seed1_n50.json", copied)
    shutil.rmtree(source)
    loaded = conv.load_convergence(results_dir=copied_dir, seed_zero_path=conv.SEED_ZERO_PATH)
    assert len(loaded.repetitions) == 1
    assert loaded.repetitions[0]["points"][0]["errors_per_receiver"] == pytest.approx([0.02, 0.02])
    sample = json.loads(copied.read_text())
    sample["metadata"]["convergence"]["exact_reference"]["record"]["fidelities"][0][0] += 0.01
    copied.write_text(json.dumps(sample))
    with pytest.raises(ValueError, match="Incompatible convergence exact reference"):
        conv.load_convergence(results_dir=copied_dir, seed_zero_path=conv.SEED_ZERO_PATH)


def test_tiny_real_collection_round_trips_actual_backend(tmp_path):
    study = conv.load_convergence(results_dir=tmp_path, seed_zero_path=conv.SEED_ZERO_PATH)
    study.config = replace(study.config, N=1, p_list=[0.0, 0.2])
    identity = conv.collect_convergence_repeats(study, repeats=1, seeds=[1], sample_counts=[2],
                                               study_id="tiny", results_dir=tmp_path)
    run = conv.load_run(tmp_path / f"run_{identity}_seed1_n2.json")
    errors = conv._measurement(run, study.config)
    assert run["seed"] == 1 and run["n_samples"] == 2
    assert errors.shape == (1,)
    assert conv.load_convergence(results_dir=tmp_path, seed_zero_path=conv.SEED_ZERO_PATH).repetitions == []


def test_portable_sample_can_resume_without_the_original_exact_file(monkeypatch, tmp_path):
    seen = _fake_backends(monkeypatch)
    study = conv.load_convergence(results_dir=tmp_path, seed_zero_path=conv.SEED_ZERO_PATH)
    conv.collect_convergence_repeats(study, repeats=1, seeds=[1], sample_counts=[50],
                                     study_id="portable", results_dir=tmp_path)
    (tmp_path / "run_portable_exact.json").unlink()
    (tmp_path / "run_portable_seed1_n50.json").rename(tmp_path / "renamed.json")
    loaded = conv.load_convergence(results_dir=tmp_path, seed_zero_path=conv.SEED_ZERO_PATH)
    before = (tmp_path / "renamed.json").read_bytes()
    conv.collect_convergence_repeats(loaded, repeats=1, seeds=[1], sample_counts=[50],
                                     study_id="portable", results_dir=tmp_path)
    assert seen == [("exact", 0, None), ("sample", 1, 50)]
    assert (tmp_path / "renamed.json").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["renamed.json"]


def test_original_seed_zero_curve_matches_current_physical_simulator(tmp_path):
    """A bounded 50-trajectory regression makes the seed-zero summary auditable."""
    from broadcasting.backend import SamplingBackend
    from broadcasting.simulation import logical_error_polynomial
    study = conv.load_convergence(results_dir=tmp_path, seed_zero_path=conv.SEED_ZERO_PATH)
    config = replace(study.config, seed=0, n_samples=50)
    sampled = SamplingBackend().run(config)
    exact_local = 1 - 2 * logical_error_polynomial(np.asarray(config.p_list)) / 3
    exact = np.repeat(exact_local[:, None], config.N, axis=1)
    errors = conv.fidelity_error(sampled.fidelities, exact, config.p_list)
    assert np.allclose(errors, study.seed_zero["errors_per_receiver"][0], rtol=0, atol=5e-9)


def test_custom_store_uses_its_own_summary_without_repository_dependency(monkeypatch, tmp_path):
    import shutil
    _fake_backends(monkeypatch)
    with pytest.raises(FileNotFoundError, match="supply seed_zero_path"):
        conv.load_convergence(results_dir=tmp_path)
    local_summary = tmp_path / "run_seed_zero.json"
    shutil.copyfile(conv.SEED_ZERO_PATH, local_summary)
    study = conv.load_convergence(results_dir=tmp_path)
    conv.collect_convergence_repeats(study, repeats=1, seeds=[1], sample_counts=[50],
                                     study_id="portable", results_dir=tmp_path)
    # An unrelated repository constant cannot become an implicit dependency.
    monkeypatch.setattr(conv, "SEED_ZERO_PATH", tmp_path / "absent.json")
    loaded = conv.load_convergence(results_dir=tmp_path)
    assert len(loaded.repetitions) == 1
    assert loaded.seed_zero["filepath"] == str(local_summary)
    assert loaded.seed_zero["fidelities"] is None


def test_interruption_before_first_sample_can_resume_a_renamed_exact_record(monkeypatch, tmp_path):
    failures = {(1, 50)}
    seen = _fake_backends(monkeypatch, failures)
    study = conv.load_convergence(results_dir=tmp_path, seed_zero_path=conv.SEED_ZERO_PATH)
    with pytest.raises(RuntimeError, match="interrupted"):
        conv.collect_convergence_repeats(study, repeats=1, seeds=[1], sample_counts=[50],
                                         study_id="portable", results_dir=tmp_path)
    (tmp_path / "run_portable_exact.json").rename(tmp_path / "renamed_exact.json")
    failures.clear()
    conv.collect_convergence_repeats(study, repeats=1, seeds=[1], sample_counts=[50],
                                     study_id="portable", results_dir=tmp_path)
    assert seen.count(("exact", 0, None)) == 1
    assert (tmp_path / "renamed_exact.json").exists()
    assert not (tmp_path / "run_portable_exact.json").exists()
