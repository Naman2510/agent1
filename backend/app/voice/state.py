"""The turn state machine (ARCHITECTURE §4.1).

`BARGED_IN` is a real state rather than a flag because cancellation is asynchronous: several
things must complete before new audio may be attributed to a new turn, and during that window the
session is neither listening nor speaking. Representing it as a flag is how you end up with two
live turns and audio attributed to the wrong one.

Transitions are declared, not implied by scattered assignments, so the legal set is reviewable and
the illegal set is testable (spec §10 requires automated tests on interruption transitions).
"""

from __future__ import annotations

from enum import StrEnum


class TurnState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    USER_SPEAKING = "user_speaking"
    THINKING = "thinking"
    SPEAKING = "speaking"
    BARGED_IN = "barged_in"
    ERROR = "error"


class Trigger(StrEnum):
    SESSION_START = "session.start"
    SPEECH_START = "vad.speech_start"
    SPEECH_END = "vad.speech_end"
    UTTERANCE_DISCARDED = "utterance.discarded"
    TURN_END = "turn.end"
    FIRST_AUDIO_QUEUED = "tts.first_chunk"
    PLAYBACK_DRAINED = "playback.drained"
    CANCELLED = "turn.cancelled"
    CANCELLATION_COMPLETE = "cancellation.complete"
    PROVIDER_FAILED = "provider.failed"
    RECOVERED = "error.recovered"
    SESSION_END = "session.end"


# (from, trigger) -> to. Anything absent is illegal by construction.
_TRANSITIONS: dict[tuple[TurnState, Trigger], TurnState] = {
    (TurnState.IDLE, Trigger.SESSION_START): TurnState.LISTENING,
    (TurnState.LISTENING, Trigger.SPEECH_START): TurnState.USER_SPEAKING,
    (TurnState.LISTENING, Trigger.SESSION_END): TurnState.IDLE,
    # Too short to be an utterance: back to listening without spending a turn.
    (TurnState.USER_SPEAKING, Trigger.UTTERANCE_DISCARDED): TurnState.LISTENING,
    (TurnState.USER_SPEAKING, Trigger.TURN_END): TurnState.THINKING,
    (TurnState.USER_SPEAKING, Trigger.SESSION_END): TurnState.IDLE,
    (TurnState.THINKING, Trigger.FIRST_AUDIO_QUEUED): TurnState.SPEAKING,
    # An empty answer, or a turn cancelled before any audio: no interruption happened.
    (TurnState.THINKING, Trigger.CANCELLED): TurnState.LISTENING,
    (TurnState.THINKING, Trigger.SPEECH_START): TurnState.BARGED_IN,
    (TurnState.THINKING, Trigger.PROVIDER_FAILED): TurnState.ERROR,
    (TurnState.SPEAKING, Trigger.PLAYBACK_DRAINED): TurnState.LISTENING,
    (TurnState.SPEAKING, Trigger.SPEECH_START): TurnState.BARGED_IN,
    (TurnState.SPEAKING, Trigger.PROVIDER_FAILED): TurnState.ERROR,
    # Cancellation has finished; the interrupting utterance is already being captured, which is
    # why this lands in USER_SPEAKING and not LISTENING.
    (TurnState.BARGED_IN, Trigger.CANCELLATION_COMPLETE): TurnState.USER_SPEAKING,
    (TurnState.BARGED_IN, Trigger.SESSION_END): TurnState.IDLE,
    (TurnState.ERROR, Trigger.RECOVERED): TurnState.LISTENING,
    (TurnState.ERROR, Trigger.SESSION_END): TurnState.IDLE,
    (TurnState.SPEAKING, Trigger.SESSION_END): TurnState.IDLE,
    (TurnState.THINKING, Trigger.SESSION_END): TurnState.IDLE,
}

# States in which the assistant is producing output, so user speech means interruption.
INTERRUPTIBLE = frozenset({TurnState.THINKING, TurnState.SPEAKING})


class IllegalTransitionError(RuntimeError):
    def __init__(self, state: TurnState, trigger: Trigger) -> None:
        super().__init__(f"{trigger} is not legal in state {state}")
        self.state = state
        self.trigger = trigger


class TurnStateMachine:
    """Holds the state and the fencing token.

    `turn_id` is monotonic and increments only when a turn genuinely ends, so a late frame can be
    recognised as belonging to a turn that is over and dropped rather than mixed into the next one.
    """

    def __init__(self) -> None:
        self._state = TurnState.IDLE
        self._turn_id = 0
        self.history: list[tuple[TurnState, Trigger, TurnState]] = []

    @property
    def state(self) -> TurnState:
        return self._state

    @property
    def turn_id(self) -> int:
        return self._turn_id

    @property
    def is_interruptible(self) -> bool:
        return self._state in INTERRUPTIBLE

    def can(self, trigger: Trigger) -> bool:
        return (self._state, trigger) in _TRANSITIONS

    def fire(self, trigger: Trigger) -> TurnState:
        try:
            destination = _TRANSITIONS[(self._state, trigger)]
        except KeyError:
            raise IllegalTransitionError(self._state, trigger) from None

        previous = self._state
        self._state = destination
        self.history.append((previous, trigger, destination))

        # A turn is finished once its output has been delivered, abandoned, or cut off. Bumping
        # here — rather than when the next turn starts — means no two turns are ever live.
        if trigger in {
            Trigger.PLAYBACK_DRAINED,
            Trigger.CANCELLATION_COMPLETE,
            Trigger.CANCELLED,
        }:
            self._turn_id += 1
        return destination

    def accepts_frame(self, frame_turn_id: int) -> bool:
        """Whether an inbound audio frame belongs to the current turn.

        Frames from a turn that has ended are dropped. Without this, audio recorded during
        cancellation is attributed to the next turn and the mentor answers a question that was
        never finished.
        """
        return frame_turn_id >= self._turn_id
