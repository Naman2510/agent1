"""Software simulation of a block-device + RAID1 storage stack.

See storage_sim/README.md for the architecture and its mapping onto real
Linux storage (mdadm, GPT partitioning, superblocks). Nothing in this
package touches a real block device — it is a from-scratch model built
entirely out of regular files, designed so that the RAID1 logic itself
(raid1.py) is agnostic to whether its members are simulated or real.
"""
