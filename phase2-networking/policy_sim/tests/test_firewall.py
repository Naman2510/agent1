"""Tests for policy_sim.firewall — SIMULATION TESTED, not real-netfilter-
tested (see firewall.py's module docstring for why, and what that
distinction means here).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from policy_sim.firewall import FirewallPolicy, Packet, TokenBucketRateLimiter  # noqa: E402

NFTABLES_CONF = Path(__file__).resolve().parent.parent.parent / "nftables" / "nftables.conf"

MGMT_IP = "10.10.100.50"
OUTSIDE_IP = "203.0.113.7"


class TestInputChain(unittest.TestCase):
    def setUp(self):
        self.fw = FirewallPolicy()

    def test_loopback_always_accepted(self):
        pkt = Packet(src_ip="127.0.0.1", iif="lo", conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt), "accept")

    def test_established_connection_accepted(self):
        pkt = Packet(src_ip=OUTSIDE_IP, conn_state="established")
        self.assertEqual(self.fw.evaluate_input(pkt), "accept")

    def test_invalid_state_dropped_even_from_management_vlan(self):
        pkt = Packet(src_ip=MGMT_IP, protocol="tcp", dst_port=22, conn_state="invalid")
        self.assertEqual(self.fw.evaluate_input(pkt), "drop")

    def test_icmp_echo_request_accepted(self):
        pkt = Packet(src_ip=OUTSIDE_IP, protocol="icmp", icmp_type="echo-request", conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt), "accept")

    def test_unrecognized_icmp_type_dropped(self):
        pkt = Packet(src_ip=OUTSIDE_IP, protocol="icmp", icmp_type="redirect", conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt), "drop")

    def test_ssh_from_management_vlan_accepted(self):
        pkt = Packet(src_ip=MGMT_IP, protocol="tcp", dst_port=22, conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt, now=0.0), "accept")

    def test_ssh_from_outside_management_vlan_dropped(self):
        pkt = Packet(src_ip=OUTSIDE_IP, protocol="tcp", dst_port=22, conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt, now=0.0), "drop")

    def test_prometheus_port_from_management_vlan_accepted(self):
        pkt = Packet(src_ip=MGMT_IP, protocol="tcp", dst_port=9100, conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt), "accept")

    def test_prometheus_port_from_outside_dropped(self):
        pkt = Packet(src_ip=OUTSIDE_IP, protocol="tcp", dst_port=9100, conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt), "drop")

    def test_redfish_port_from_management_vlan_accepted(self):
        pkt = Packet(src_ip=MGMT_IP, protocol="tcp", dst_port=8443, conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt), "accept")

    def test_arbitrary_port_from_management_vlan_still_dropped(self):
        # Being on the management VLAN isn't a blanket allow — only the
        # three explicitly listed ports/services are.
        pkt = Packet(src_ip=MGMT_IP, protocol="tcp", dst_port=3389, conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt), "drop")

    def test_ssh_rate_limit_enforced_then_recovers(self):
        # burst=40 at rate=20/s: the first 40 in a burst succeed, the
        # 41st in the same instant is rate-limited (and thus dropped,
        # since no other rule matches), and after enough time passes for
        # the bucket to refill, traffic is accepted again.
        for i in range(40):
            pkt = Packet(src_ip=MGMT_IP, protocol="tcp", dst_port=22, conn_state="new")
            self.assertEqual(self.fw.evaluate_input(pkt, now=0.0), "accept", f"packet {i} should fit in the burst")

        pkt = Packet(src_ip=MGMT_IP, protocol="tcp", dst_port=22, conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt, now=0.0), "drop", "41st packet in the same instant must be rate-limited")

        # 1 full second later, the bucket has refilled by 20 tokens.
        pkt = Packet(src_ip=MGMT_IP, protocol="tcp", dst_port=22, conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt, now=1.0), "accept")

    def test_rate_limit_is_per_source_ip_not_global(self):
        other_mgmt_ip = "10.10.100.51"
        for _ in range(40):
            self.fw.evaluate_input(Packet(src_ip=MGMT_IP, protocol="tcp", dst_port=22, conn_state="new"), now=0.0)
        # MGMT_IP's bucket is now exhausted, but a different source IP's
        # bucket must be completely independent.
        pkt = Packet(src_ip=other_mgmt_ip, protocol="tcp", dst_port=22, conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt, now=0.0), "accept")

    def test_default_policy_is_drop(self):
        pkt = Packet(src_ip=OUTSIDE_IP, protocol="tcp", dst_port=443, conn_state="new")
        self.assertEqual(self.fw.evaluate_input(pkt), "drop")


class TestForwardChain(unittest.TestCase):
    def setUp(self):
        self.fw = FirewallPolicy()

    def test_diag_ns_to_eth0_new_connection_accepted(self):
        pkt = Packet(src_ip="169.254.100.2", iif="veth-diag-n", oif="eth0", conn_state="new")
        self.assertEqual(self.fw.evaluate_forward(pkt), "accept")

    def test_diag_ns_to_a_different_output_interface_dropped(self):
        # The rule requires oifname eth0 specifically — diag-ns must
        # never be forwarded back into an internal interface.
        pkt = Packet(src_ip="169.254.100.2", iif="veth-diag-n", oif="eth1", conn_state="new")
        self.assertEqual(self.fw.evaluate_forward(pkt), "drop")

    def test_established_forward_traffic_accepted(self):
        pkt = Packet(src_ip="169.254.100.2", iif="veth-diag-n", oif="eth0", conn_state="established")
        self.assertEqual(self.fw.evaluate_forward(pkt), "accept")

    def test_non_diag_ns_forward_traffic_dropped_by_default(self):
        pkt = Packet(src_ip=OUTSIDE_IP, iif="eth0", oif="eth1", conn_state="new")
        self.assertEqual(self.fw.evaluate_forward(pkt), "drop")


class TestOutputChain(unittest.TestCase):
    def setUp(self):
        self.fw = FirewallPolicy()

    def test_loopback_output_accepted(self):
        pkt = Packet(src_ip="127.0.0.1", oif="lo")
        self.assertEqual(self.fw.evaluate_output(pkt), "accept")

    def test_dns_udp_and_tcp_both_accepted(self):
        self.assertEqual(self.fw.evaluate_output(Packet(src_ip="10.10.0.10", protocol="udp", dst_port=53)), "accept")
        self.assertEqual(self.fw.evaluate_output(Packet(src_ip="10.10.0.10", protocol="tcp", dst_port=53)), "accept")

    def test_ntp_udp_accepted_but_not_tcp(self):
        self.assertEqual(self.fw.evaluate_output(Packet(src_ip="10.10.0.10", protocol="udp", dst_port=123)), "accept")
        self.assertEqual(self.fw.evaluate_output(Packet(src_ip="10.10.0.10", protocol="tcp", dst_port=123)), "drop")

    def test_http_and_https_accepted(self):
        self.assertEqual(self.fw.evaluate_output(Packet(src_ip="10.10.0.10", protocol="tcp", dst_port=80)), "accept")
        self.assertEqual(self.fw.evaluate_output(Packet(src_ip="10.10.0.10", protocol="tcp", dst_port=443)), "accept")

    def test_ssh_egress_accepted(self):
        self.assertEqual(self.fw.evaluate_output(Packet(src_ip="10.10.0.10", protocol="tcp", dst_port=22)), "accept")

    def test_arbitrary_egress_port_dropped(self):
        self.assertEqual(self.fw.evaluate_output(Packet(src_ip="10.10.0.10", protocol="tcp", dst_port=6667)), "drop")

    def test_established_egress_always_accepted_even_on_a_normally_blocked_port(self):
        pkt = Packet(src_ip="10.10.0.10", protocol="tcp", dst_port=6667, conn_state="established")
        self.assertEqual(self.fw.evaluate_output(pkt), "accept")


class TestTokenBucketRateLimiter(unittest.TestCase):
    def test_burst_capacity_then_exhaustion(self):
        limiter = TokenBucketRateLimiter(rate_per_second=10, burst=5)
        results = [limiter.allow("1.2.3.4", now=0.0) for _ in range(6)]
        self.assertEqual(results, [True, True, True, True, True, False])

    def test_refill_over_time(self):
        limiter = TokenBucketRateLimiter(rate_per_second=10, burst=5)
        for _ in range(5):
            limiter.allow("1.2.3.4", now=0.0)
        self.assertFalse(limiter.allow("1.2.3.4", now=0.0))
        # 0.5s later at 10/s = 5 tokens refilled.
        self.assertTrue(limiter.allow("1.2.3.4", now=0.5))

    def test_independent_keys(self):
        limiter = TokenBucketRateLimiter(rate_per_second=1, burst=1)
        self.assertTrue(limiter.allow("a", now=0.0))
        self.assertTrue(limiter.allow("b", now=0.0))
        self.assertFalse(limiter.allow("a", now=0.0))
        self.assertFalse(limiter.allow("b", now=0.0))


class TestConsistencyWithRealConfigFile(unittest.TestCase):
    """This simulation is a hand-maintained duplicate of nftables.conf's
    logic, not derived from parsing it — see firewall.py's module
    docstring for why. This is the mitigation for that drift risk: if a
    port number, CIDR, or rate limit changes in the real file without a
    matching update here, these assertions fail loudly instead of the
    two silently disagreeing forever."""

    def setUp(self):
        if not NFTABLES_CONF.exists():
            self.skipTest(f"{NFTABLES_CONF} not found")
        self.text = NFTABLES_CONF.read_text()

    def test_management_vlan_cidr_matches(self):
        self.assertIn("10.10.100.0/24", self.text)

    def test_diag_ns_subnet_matches(self):
        self.assertIn("169.254.100.0/30", self.text)

    def test_ssh_rate_limit_values_match(self):
        self.assertIn("limit rate 20/second burst 40 packets", self.text)

    def test_monitored_ports_match(self):
        for port in ("22", "9100", "8443"):
            self.assertIn(port, self.text)

    def test_egress_ports_match(self):
        for port in ("53", "123", "80", "443", "22"):
            self.assertIn(port, self.text)

    def test_diag_ns_interface_pattern_matches(self):
        self.assertIn("veth-diag", self.text)


if __name__ == "__main__":
    unittest.main()
