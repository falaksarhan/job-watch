"""Tests for the three gates and the digest. Run: python3 -m unittest"""
import os
import unittest

import scan

P = scan.load_profile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.json"))


class TitleGate(unittest.TestCase):
    def test_operations_roles_pass(self):
        for t in ["AI Operations Manager", "Head of AI Automation", "Forward Deployed Strategist",
                  "Chief of Staff", "Business Systems Lead, Automation", "Odoo Consultant"]:
            self.assertTrue(scan.title_ok(t, P), t)

    def test_engineering_product_and_marketing_roles_fail(self):
        for t in ["AI Engineer", "Senior Software Developer", "AI Product Manager", "Growth Operations Manager",
                  "AI Operations Intern", "Machine Learning Operations Lead", "Customer Success Manager, AI"]:
            self.assertFalse(scan.title_ok(t, P), t)

    def test_german_language_postings_fail(self):
        self.assertFalse(scan.title_ok("AI Operations Manager (m/w/d)", P))
        self.assertFalse(scan.title_ok("Leiter Automatisierung", P))

    def test_title_pinned_to_another_country_fails(self):
        self.assertFalse(scan.title_ok("Deployment Strategist - Italy", P))
        self.assertFalse(scan.title_ok("AI Operations Lead (Paris)", P))
        self.assertTrue(scan.title_ok("AI Operations Lead, Europe", P))
        self.assertTrue(scan.title_ok("AI Operations Lead - Austria", P))

    def test_founders_associate_only_without_junior(self):
        self.assertTrue(scan.title_ok("Founder's Associate", P))
        self.assertFalse(scan.title_ok("Junior Founder's Associate", P))


class LocationGate(unittest.TestCase):
    def test_home_ok(self):
        self.assertTrue(scan.home_ok("Remote, EMEA", P))
        self.assertTrue(scan.home_ok("Remote Austria", P))
        self.assertTrue(scan.home_ok("Remote", P))
        self.assertFalse(scan.home_ok("Remote, Germany", P))
        self.assertFalse(scan.home_ok("Remote Spain, Portugal", P))

    def test_loc_ok(self):
        self.assertTrue(scan.loc_ok("Remote Europe"))
        self.assertTrue(scan.loc_ok("Worldwide, United States"))
        self.assertFalse(scan.loc_ok("New York, United States"))
        self.assertFalse(scan.loc_ok("Beirut"))


class RemoteGate(unittest.TestCase):
    def setUp(self):
        for k in scan.DROPPED:
            scan.DROPPED[k] = 0

    def test_hybrid_is_not_remote(self):
        self.assertFalse(scan.remote_verdict("Remote role, hybrid: 3 days per week in our Berlin office"))
        self.assertFalse(scan.remote_verdict("<p>We work remotely but you will relocate to Amsterdam.</p>"))
        self.assertEqual(scan.DROPPED["hybrid/on-site"], 2)

    def test_country_restriction_outside_europe(self):
        self.assertFalse(scan.remote_verdict("Fully remote. You must be based in the United States."))
        self.assertTrue(scan.remote_verdict("Fully remote within Europe. Must be based in the US or the EU."))

    def test_strong_and_weak_remote_signals(self):
        self.assertTrue(scan.remote_verdict("This is a remote-first team across EMEA."))
        self.assertTrue(scan.remote_verdict("You may work from home or from a coworking space."))
        self.assertFalse(scan.remote_verdict("A great role in a great team. Apply now."))
        self.assertEqual(scan.DROPPED["no remote signal"], 1)

    def test_board_flag_without_description(self):
        self.assertTrue(scan.remote_verdict("", workplace="remote"))
        self.assertIsNone(scan.remote_verdict(""))
        self.assertFalse(scan.remote_verdict("", workplace="hybrid"))


class AddAndDigest(unittest.TestCase):
    def test_add_keeps_only_postings_that_pass_all_gates(self):
        out = {}
        scan.add(out, P, "AI Operations Manager", "acme", "Remote EMEA", "https://x/1", desc="Fully remote across Europe.")
        scan.add(out, P, "AI Operations Manager", "acme", "Remote EMEA", "https://x/2", desc="Hybrid, 2 days in the office.")
        scan.add(out, P, "AI Engineer", "acme", "Remote EMEA", "https://x/3", desc="Fully remote.")
        scan.add(out, P, "Head of Operations", "acme", "Remote EMEA", "https://x/4", desc="Fully remote. Finance and HR.")
        scan.add(out, P, "Head of Operations", "acme", "Remote EMEA", "https://x/5", desc="Fully remote. You will roll out AI agents.")
        self.assertEqual(sorted(out), ["https://x/1", "https://x/5"])

    def test_same_role_per_country_collapses_to_one_line(self):
        new = {
            "https://x/a": {"title": "AI Ops Lead", "company": "Jobgether", "loc": "Remote Austria", "date": ""},
            "https://x/b": {"title": "AI Ops Lead", "company": "jobgether", "loc": "Remote Spain", "date": ""},
            "https://x/c": {"title": "Automation Manager", "company": "Acme", "loc": "Remote", "date": ""},
        }
        groups = scan.group_matches(new)
        self.assertEqual([g["v"]["company"] for g in groups], ["Acme", "Jobgether"])
        text = scan.digest({"f": 1, "g": 2, "h": 3, "i": 4}, new, groups, today="2026-10-26")
        self.assertTrue(text.startswith("Job watch 2026-10-26: 2 new match(es) (3 postings) out of 4 current"))
        self.assertIn("2 countries incl. Remote Austria", text)
        self.assertIn("https://x/c", text)


if __name__ == "__main__":
    unittest.main()
