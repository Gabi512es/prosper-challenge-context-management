"""Offline: the v4 call's end-of-turn switch (Smart Turn v3 by default, silence
timeout when off or when the model does not load). Loads the bundled ONNX model
from the installed Pipecat package; no network."""
import unittest

from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy, TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from v4_bot import SMART_TURN_ENV, turn_stop


class SmartTurnSwitchTest(unittest.TestCase):
    def test_on_by_default(self):
        for env in ({}, {SMART_TURN_ENV: ''}, {SMART_TURN_ENV: '1'}, {SMART_TURN_ENV: 'on'}):
            with self.subTest(env=env):
                stop, record = turn_stop(env)
                self.assertEqual(len(stop), 1)
                self.assertIsInstance(stop[0], TurnAnalyzerUserTurnStopStrategy)
                self.assertIsInstance(stop[0]._turn_analyzer, LocalSmartTurnAnalyzerV3)
                self.assertEqual(record['mode'], 'smart_turn_v3')
                self.assertEqual(record['analyzer'], 'LocalSmartTurnAnalyzerV3')

    def test_off_uses_the_silence_timeout(self):
        for value in ('0', 'false', 'OFF', 'no'):
            with self.subTest(value=value):
                stop, record = turn_stop({SMART_TURN_ENV: value})
                self.assertIsInstance(stop[0], SpeechTimeoutUserTurnStopStrategy)
                self.assertEqual((record['mode'], record['reason']), ('speech_timeout', 'disabled'))

    def test_a_model_that_does_not_load_falls_back_and_says_why(self):
        def broken():
            raise OSError('model file missing')
        stop, record = turn_stop({}, analyzer=broken)
        self.assertIsInstance(stop[0], SpeechTimeoutUserTurnStopStrategy)
        self.assertEqual(record, dict(mode='speech_timeout', reason='load_failed', user_speech_timeout_secs=0.6,
                                      env='1', error_type='OSError'))

    def test_the_chosen_strategy_is_the_one_used(self):
        # An explicit stop list replaces Pipecat's default (which would load the model again).
        for env in ({}, {SMART_TURN_ENV: '0'}):
            stop, _ = turn_stop(env)
            self.assertIs(UserTurnStrategies(stop=stop).stop[0], stop[0])


if __name__ == '__main__':
    unittest.main()
