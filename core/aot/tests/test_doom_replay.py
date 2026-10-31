import json
import unittest

from examples.doom.verify import CAPTURES, HERE, capture_tics, digest


class ReplayTests(unittest.TestCase):
    def trace(self, tics=(78, 79, 80, 858, 859, 860)):
        return ''.join(f'aot-replay frame={frame} tic={tic}\n' for frame, tic in zip(CAPTURES, tics)) + 'aot-replay final-tic=5026\n'

    def test_selection_uses_observed_tic(self):
        self.assertEqual(capture_tics(self.trace(), 5026)[79], 120)
        shifted = capture_tics(self.trace((79, 80, 81, 859, 860, 861)), 5026)
        self.assertEqual((shifted[79], shifted[859]), (119, 899))

    def test_missing_or_duplicate_capture_rejected(self):
        for text in [self.trace().replace('aot-replay frame=120 tic=79\n', ''), self.trace() + 'aot-replay frame=120 tic=79\n']:
            with self.assertRaises(ValueError):
                capture_tics(text, 5026)

    def test_wipe_and_nonmonotonic_tics_rejected(self):
        for tics in [(1, 1, 1, 858, 859, 860), (80, 79, 81, 858, 859, 860)]:
            with self.assertRaises(ValueError):
                capture_tics(self.trace(tics), 5026)

    def test_wrong_final_tic_rejected(self):
        with self.assertRaises(ValueError):
            capture_tics(self.trace(), 3836)

    def test_measured_runtime_sources_pinned(self):
        root = HERE.parents[3]
        sources = json.loads((HERE / 'bindings.json').read_text())['sources']
        for name in ['core/libs/prx/libSceSystemService/LoadExec.cpp', 'core/libs/prx/libScePad/src/PadState.cpp',
                     'core/libs/prx/libkernel/Pthread/src/Mutex.cpp', 'core/libs/prx/libkernel/Time/SleepWake.cpp']:
            self.assertEqual(sources.get(name), digest(root / name), name)


if __name__ == '__main__':
    unittest.main()
