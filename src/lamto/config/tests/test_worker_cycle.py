from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from lamto.config.worker import (
    CycleResult,
    ProcessorResult,
    process_notifications_batch,
    run_worker_cycle,
)


class WorkerCycleTests(TestCase):
    def test_failed_adapter_does_not_stop_other_queues(self):
        def boom(**kwargs):
            raise RuntimeError("triage down")

        def ok_notifications(**kwargs):
            return ProcessorResult(name="notifications", ok=True, count=0, detail="ok")

        with patch(
            "lamto.config.worker.PROCESSORS",
            (
                boom,
                ok_notifications,
            ),
        ):
            result = run_worker_cycle()

        self.assertEqual(len(result.processors), 2)
        self.assertFalse(result.processors[0].ok)
        self.assertIn("triage down", result.processors[0].detail)
        self.assertTrue(result.processors[1].ok)

    def test_processor_result_isolation_with_real_notifications(self):
        # Notifications batch should succeed even if empty
        res = process_notifications_batch(limit=5)
        self.assertTrue(res.ok)
        self.assertEqual(res.name, "notifications")

    def test_cycle_runs_all_named_processors(self):
        with patch(
            "lamto.config.worker.process_triage_batch",
            return_value=ProcessorResult("triage", True),
        ), patch(
            "lamto.config.worker.process_emergency_outcomes_batch",
            return_value=ProcessorResult("emergency_outcomes", True),
        ), patch(
            "lamto.config.worker.process_blockchain_outbox_batch",
            return_value=ProcessorResult("blockchain_outbox", True),
        ), patch(
            "lamto.config.worker.process_publication_finalization_batch",
            return_value=ProcessorResult("publication_finalize", True),
        ), patch(
            "lamto.config.worker.process_integrity_batch",
            return_value=ProcessorResult("integrity", True),
        ), patch(
            "lamto.config.worker.process_notifications_batch",
            return_value=ProcessorResult("notifications", True),
        ):
            # PROCESSORS tuple holds real callables; patch the functions they reference
            # by replacing PROCESSORS with patched callables
            from lamto.config import worker as worker_mod

            patched = (
                worker_mod.process_triage_batch,
                worker_mod.process_emergency_outcomes_batch,
                worker_mod.process_blockchain_outbox_batch,
                worker_mod.process_publication_finalization_batch,
                worker_mod.process_integrity_batch,
                worker_mod.process_notifications_batch,
            )
            with patch.object(worker_mod, "PROCESSORS", patched):
                # The patches above wrap the names but PROCESSORS already bound
                # originals. Force new PROCESSORS of MagicMocks instead:
                pass

        calls = []

        def make(name, fail=False):
            def _fn(**kwargs):
                calls.append(name)
                if fail:
                    raise RuntimeError(f"{name} failed")
                return ProcessorResult(name=name, ok=True, count=0)

            return _fn

        processors = (
            make("triage"),
            make("emergency_outcomes", fail=True),
            make("blockchain_outbox"),
            make("publication_finalize"),
            make("integrity"),
            make("notifications"),
        )
        with patch("lamto.config.worker.PROCESSORS", processors):
            result = run_worker_cycle()

        self.assertEqual(
            calls,
            [
                "triage",
                "emergency_outcomes",
                "blockchain_outbox",
                "publication_finalize",
                "integrity",
                "notifications",
            ],
        )
        self.assertFalse(result.all_ok)
        self.assertTrue(result.processors[0].ok)
        self.assertFalse(result.processors[1].ok)
        self.assertTrue(result.processors[2].ok)
        self.assertTrue(result.processors[-1].ok)
