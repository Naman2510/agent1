# Unit 8: Guided Electromagnetic Waves

## Chapter 19: Waveguides

### 19.1 Why a hollow conductor guides waves

A waveguide is typically a hollow conducting tube — rectangular or circular in cross-section — that
confines and directs electromagnetic waves along its length. Unlike a transmission line, which
carries a wave as a voltage and current on a pair of conductors, a waveguide carries the wave as an
electromagnetic field pattern filling the interior, bounded by the conducting walls.

Because the walls are (ideally) perfect conductors, the tangential electric field at the wall must
be zero. This boundary condition is the reason a waveguide only supports certain field patterns,
called **modes**, rather than an arbitrary wave shape. Each mode has a characteristic field
distribution across the cross-section and a **cutoff frequency**: below this frequency, that mode
cannot propagate at all — the wave decays exponentially instead of travelling.

### 19.2 TE and TM modes

Waveguide modes are classified by which field component lies entirely in the plane transverse to
the direction of propagation:

- **TE (transverse electric) modes**: the electric field has no component along the direction of
  propagation; the magnetic field does.
- **TM (transverse magnetic) modes**: the magnetic field has no component along the direction of
  propagation; the electric field does.

A rectangular waveguide's modes are labelled TE_mn or TM_mn, where m and n count the half-wave
variations of the field across the two transverse dimensions. The TE_10 mode has the lowest cutoff
frequency of any mode in a standard rectangular waveguide and is therefore the mode used in most
practical waveguide systems — operating above its cutoff but below the cutoff of the next mode
keeps the guide single-moded, avoiding the signal distortion that occurs when multiple modes
propagate simultaneously at different speeds.

### 19.3 Waveguide impedance

The **wave impedance** inside a waveguide — the ratio of transverse electric to transverse magnetic
field — is not the same as a transmission line's characteristic impedance, and it depends on
frequency, unlike the (frequency-independent) impedance of a TEM transmission line. For a TE mode,
the wave impedance rises without bound as the operating frequency approaches the mode's cutoff
frequency from above; for a TM mode, it falls towards zero at cutoff. This frequency dependence has
no analogue in ordinary two-conductor transmission line theory and is a common source of confusion
for students moving from transmission lines to waveguides for the first time.

### 19.4 Why this topic is considered difficult

Waveguide theory requires holding several things in mind simultaneously: the mode's field pattern,
its cutoff frequency, its wave impedance, and how these change with the waveguide's physical
dimensions. Unlike Kirchhoff's laws or even Maxwell's equations in integral form, there is no single
equation that summarises the behaviour — the field pattern itself must be derived from the wave
equation subject to the boundary conditions, which is usually the first place in the course a
student has to solve a genuine partial differential equation with boundary conditions rather than
apply a named law directly.
