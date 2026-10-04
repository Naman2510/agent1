"""The turn state machine: every legal transition, and the illegal ones (spec §10).

A state machine whose illegal transitions are untested is a state machine that will silently
accept them in production. Since barge-in correctness is defined by these transitions, the
exhaustive matrix is the test.
"""

from __future__ import annotations

import itertools

import pytest

from app.voice.state import (
    INTERRUPTIBLE,
    IllegalTransitionError,
    Trigger,
    TurnState,
    TurnStateMachine,
)

LEGAL: set[tuple[TurnState, Trigger]] = {
    (TurnState.IDLE, Trigger.SESSION_START),
    (TurnState.LISTENING, Trigger.SPEECH_START),
    (TurnState.LISTENING, Trigger.SESSION_END),
    (TurnState.USER_SPEAKING, Trigger.UTTERANCE_DISCARDED),
    (TurnState.USER_SPEAKING, Trigger.TURN_END),
    (TurnState.USER_SPEAKING, Trigger.SESSION_END),
    (TurnState.THINKING, Trigger.FIRST_AUDIO_QUEUED),
    (TurnState.THINKING, Trigger.CANCELLED),
    (TurnState.THINKING, Trigger.SPEECH_START),
    (TurnState.THINKING, Trigger.PROVIDER_FAILED),
    (TurnState.THINKING, Trigger.SESSION_END),
    (TurnState.SPEAKING, Trigger.PLAYBACK_DRAINED),
    (TurnState.SPEAKING, Trigger.SPEECH_START),
    (TurnState.SPEAKING, Trigger.PROVIDER_FAILED),
    (TurnState.SPEAKING, Trigger.SESSION_END),
    (TurnState.BARGED_IN, Trigger.CANCELLATION_COMPLETE),
    (TurnState.BARGED_IN, Trigger.SESSION_END),
    (TurnState.ERROR, Trigger.RECOVERED),
    (TurnState.ERROR, Trigger.SESSION_END),
}


def _machine_in(state: TurnState) -> TurnStateMachine:
    """Drive a machine into a state through legal transitions only."""
    machine = TurnStateMachine()
    paths: dict[TurnState, list[Trigger]] = {
        TurnState.IDLE: [],
        TurnState.LISTENING: [Trigger.SESSION_START],
        TurnState.USER_SPEAKING: [Trigger.SESSION_START, Trigger.SPEECH_START],
        TurnState.THINKING: [Trigger.SESSION_START, Trigger.SPEECH_START, Trigger.TURN_END],
        TurnState.SPEAKING: [
            Trigger.SESSION_START,
            Trigger.SPEECH_START,
            Trigger.TURN_END,
            Trigger.FIRST_AUDIO_QUEUED,
        ],
        TurnState.BARGED_IN: [
            Trigger.SESSION_START,
            Trigger.SPEECH_START,
            Trigger.TURN_END,
            Trigger.FIRST_AUDIO_QUEUED,
            Trigger.SPEECH_START,
        ],
        TurnState.ERROR: [
            Trigger.SESSION_START,
            Trigger.SPEECH_START,
            Trigger.TURN_END,
            Trigger.PROVIDER_FAILED,
        ],
    }
    for trigger in paths[state]:
        machine.fire(trigger)
    assert machine.state is state
    return machine


@pytest.mark.parametrize(("state", "trigger"), sorted(LEGAL, key=lambda p: (p[0], p[1])))
def test_legal_transitions_are_accepted(state: TurnState, trigger: Trigger) -> None:
    machine = _machine_in(state)
    assert machine.can(trigger)
    machine.fire(trigger)


@pytest.mark.parametrize(
    ("state", "trigger"),
    sorted(
        {pair for pair in itertools.product(TurnState, Trigger) if pair not in LEGAL},
        key=lambda p: (p[0], p[1]),
    ),
)
def test_illegal_transitions_raise(state: TurnState, trigger: Trigger) -> None:
    """The exhaustive complement. 49 pairs the machine must refuse."""
    machine = _machine_in(state)
    assert not machine.can(trigger)
    with pytest.raises(IllegalTransitionError):
        machine.fire(trigger)


def test_the_machine_starts_idle_with_turn_zero() -> None:
    machine = TurnStateMachine()
    assert machine.state is TurnState.IDLE
    assert machine.turn_id == 0


def test_only_thinking_and_speaking_are_interruptible() -> None:
    """Interrupting while listening is just speaking; it must not trigger cancellation."""
    assert {TurnState.THINKING, TurnState.SPEAKING} == INTERRUPTIBLE
    for state in TurnState:
        assert _machine_in(state).is_interruptible == (state in INTERRUPTIBLE)


def test_a_completed_turn_advances_the_fencing_token() -> None:
    machine = _machine_in(TurnState.SPEAKING)
    assert machine.turn_id == 0
    machine.fire(Trigger.PLAYBACK_DRAINED)
    assert machine.turn_id == 1


def test_a_barged_in_turn_advances_the_fencing_token() -> None:
    machine = _machine_in(TurnState.BARGED_IN)
    assert machine.turn_id == 0
    machine.fire(Trigger.CANCELLATION_COMPLETE)
    assert machine.turn_id == 1
    assert machine.state is TurnState.USER_SPEAKING


def test_an_abandoned_turn_advances_the_fencing_token() -> None:
    machine = _machine_in(TurnState.THINKING)
    machine.fire(Trigger.CANCELLED)
    assert machine.turn_id == 1
    assert machine.state is TurnState.LISTENING


def test_the_token_does_not_advance_on_intermediate_transitions() -> None:
    """Only the end of a turn bumps it; otherwise two turns could be live at once."""
    machine = TurnStateMachine()
    for trigger in (
        Trigger.SESSION_START,
        Trigger.SPEECH_START,
        Trigger.TURN_END,
        Trigger.FIRST_AUDIO_QUEUED,
    ):
        machine.fire(trigger)
        assert machine.turn_id == 0


def test_frames_from_a_finished_turn_are_rejected() -> None:
    """The fencing rule: audio recorded during cancellation must not leak into the next turn."""
    machine = _machine_in(TurnState.SPEAKING)
    assert machine.accepts_frame(0) is True
    machine.fire(Trigger.PLAYBACK_DRAINED)  # turn_id -> 1
    assert machine.accepts_frame(0) is False
    assert machine.accepts_frame(1) is True
    # A client that races ahead is tolerated; a client that lags is not.
    assert machine.accepts_frame(2) is True


def test_transitions_are_recorded_for_diagnosis() -> None:
    machine = _machine_in(TurnState.SPEAKING)
    assert machine.history[0] == (TurnState.IDLE, Trigger.SESSION_START, TurnState.LISTENING)
    assert machine.history[-1][2] is TurnState.SPEAKING
