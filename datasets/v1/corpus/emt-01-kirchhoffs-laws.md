# Unit 3: Circuit Fundamentals

## Chapter 7: Kirchhoff's Laws

### 7.1 Kirchhoff's Voltage Law

Kirchhoff's Voltage Law, usually written KVL, states that the sum of all potential differences
around any closed loop in a circuit is zero. This follows directly from conservation of energy: if
a charge returns to its starting point after travelling around a loop, the net work done on it
must be zero, because it is back where it started with the same potential energy.

Formally, for a loop with n circuit elements:

    V_1 + V_2 + ... + V_n = 0

where each V_i is taken with a sign convention: positive when the loop direction moves from the
minus to the plus terminal of an element, negative otherwise. Students most often lose marks by
choosing an inconsistent sign convention partway around the loop, not by making an arithmetic
error.

**Worked example.** A loop with a 12 V source and two resistors of 3 kΩ and 3.5 kΩ in series
carries a current I. Applying KVL around the loop:

    12 - I(3000) - I(3500) = 0
    I = 12 / 6500 ≈ 1.846 mA

The voltage across the 3.5 kΩ resistor is therefore approximately 6.46 V.

### 7.2 Kirchhoff's Current Law

Kirchhoff's Current Law, KCL, states that the sum of currents entering any node equals the sum of
currents leaving it. This is conservation of charge: charge cannot accumulate at an ideal node.

    sum(I_in) = sum(I_out)

KCL and KVL together, applied systematically to every independent loop and node, are sufficient to
solve any linear circuit — this is the basis of both mesh analysis and nodal analysis, covered in
the network theorems chapter.

### 7.3 Common student confusion: KVL vs KCL

A frequent doubt is which law applies to voltage and which to current. A simple way to remember
it: Kirchhoff's *Voltage* Law is about loops (a voltage is measured around a path); Kirchhoff's
*Current* Law is about nodes (current is measured at a point). If a question describes a closed
path, reach for KVL; if it describes a junction where wires meet, reach for KCL.

Both laws hold regardless of what the circuit elements are — resistors, capacitors, inductors, or
sources — because they follow from charge and energy conservation, not from any particular
element's behaviour.
