# Unit 3: Circuit Fundamentals

## Chapter 9: Network Theorems

### 9.1 Mesh analysis

Mesh analysis assigns a circulating mesh current to each independent loop of a planar circuit and
writes one KVL equation per mesh in terms of these currents, rather than the branch currents
directly. For a circuit with m independent meshes, this produces m simultaneous equations in m
unknowns — fewer equations than writing KVL for every branch individually, which is the main
practical advantage of the method.

**Steps**: (1) identify each independent loop and assign a mesh current, conventionally clockwise;
(2) for each mesh, write KVL by summing voltage drops around that loop, expressing every resistor
drop in terms of the mesh currents flowing through it (a resistor shared between two meshes carries
the difference of the two mesh currents); (3) solve the resulting linear system.

### 9.2 Nodal analysis

Nodal analysis is the dual approach: it assigns an unknown voltage to every node except a chosen
reference (ground) node, and writes one KCL equation per non-reference node, expressing each
branch current via Ohm's law in terms of the node voltages at its two ends. For a circuit with n
non-reference nodes, this produces n simultaneous equations.

Nodal analysis is generally preferred when a circuit has few nodes and many meshes; mesh analysis
is preferred in the opposite case. Both methods always produce the same answer for any given
circuit — the choice is purely about which produces fewer equations to solve by hand.

### 9.3 Thevenin's and Norton's theorems

Thevenin's theorem states that any linear two-terminal network, however complicated, can be
replaced — as seen from those two terminals — by a single voltage source in series with a single
resistor. Norton's theorem is the dual statement: the same network can be replaced by a single
current source in parallel with a single resistor. The two are related by a straightforward
source transformation.

These theorems are most useful when a single component's behaviour is of interest and the rest of
the network is fixed: rather than re-solving the whole network for every trial value of that one
component, the network is reduced once to its Thevenin (or Norton) equivalent, and the component of
interest is analysed against that much simpler equivalent circuit.

### 9.4 Superposition

The superposition theorem states that in a linear circuit with multiple independent sources, the
response (a voltage or current) at any point equals the sum of the responses caused by each source
acting alone, with every other independent source suppressed — voltage sources replaced by short
circuits, current sources replaced by open circuits. Superposition applies only to linear circuits
and only to independent sources; a dependent source must never be suppressed, because its value
depends on a variable elsewhere in the circuit.
