# Unit 4: Time-Domain Circuit Analysis

## Chapter 11: Transient Response

### 11.1 What a transient is

A transient is the temporary part of a circuit's response that occurs immediately after a sudden
change — a switch closing, a source stepping to a new value — before the circuit settles into its
new steady state. Only circuits containing energy-storage elements, capacitors or inductors,
exhibit transients; a purely resistive circuit responds instantaneously to any change.

### 11.2 First-order RC and RL circuits

A circuit with a single capacitor (and otherwise only resistors and sources) or a single inductor
is called first-order, because its behaviour is governed by a first-order differential equation.
For a series RC circuit charging from a step voltage V_s, the capacitor voltage evolves as:

    v_C(t) = V_s (1 - e^(-t/RC))

where the product RC is the circuit's **time constant**, denoted τ. After one time constant, the
capacitor has reached approximately 63.2% of its final value; after five time constants, it is
considered to have reached steady state for most practical purposes. An RL circuit follows the
same exponential form with time constant τ = L/R.

### 11.3 Second-order RLC circuits

A circuit containing both a capacitor and an inductor is second-order, governed by a second-order
differential equation, and its behaviour depends on the relationship between two parameters: the
damping factor and the natural (undamped) resonant frequency. Three qualitatively different
responses are possible:

- **Overdamped**: the response returns to steady state without oscillating, more slowly than the
  critically damped case.
- **Critically damped**: the fastest possible return to steady state without any oscillation.
- **Underdamped**: the response oscillates with gradually decaying amplitude before settling.

Which case applies depends only on the circuit's component values, not on the size or nature of the
applied step — changing the source only scales the response, it does not change which of the three
qualitative behaviours occurs.

### 11.4 Common confusion: transient vs steady-state analysis

Steady-state AC analysis (phasors, impedance) and transient analysis solve different questions and
use different tools. Phasor analysis assumes a sinusoidal source has been applied for a long time
and asks only about the resulting sinusoidal response, discarding any transient that has already
decayed away. Transient analysis is precisely about that decaying part, and is needed whenever a
circuit has recently experienced a sudden change — a switch operation, a fault, a step input — and
the behaviour during the first few time constants matters.
