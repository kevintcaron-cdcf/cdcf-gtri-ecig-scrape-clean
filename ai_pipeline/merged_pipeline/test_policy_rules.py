"""Regression and guardrail tests for the reusable-product Disposable rescues.

These tests use representative listing language rather than any brand-specific rule.
Run with: python -m unittest -v test_policy_rules.py
"""

import unittest

import policy_rules as rules


def classify_as_disposable(name, description, combo=True):
    """Apply policy to a model Disposable answer with a minimal source row."""
    return rules.apply_category_policy(
        {
            "categories": rules.DISPOSABLE,
            "rationale": "Model selected a marketed disposable.",
            "combination_device": combo,
        },
        {
            "product_name": name,
            "site_category": "disposables",
            "site_tag": "",
            "description": description,
            "eliquid_contents": "",
        },
    )


class DisposableReusableRolePolicyTests(unittest.TestCase):
    def assert_rescue(self, name, description, category, rule_id):
        result = classify_as_disposable(name, description)
        self.assertEqual(category, result["categories"])
        self.assertEqual(rule_id, result["policy_rule_id"])
        # R9 must remove the downstream combo false positive after a category rescue.
        self.assertFalse(result["combination_device"])
        self.assertEqual("R9_CLEARED_NON_DISPOSABLE", result["combo_rule_applied"])

    def test_prefilled_pod_with_separate_named_host_is_closed_refills(self):
        self.assert_rescue(
            "Lost Mary Psyper Prefilled Pod Kit 2500 & 5500 Puffs",
            "The pre-filled replaceable pod provides 5% nicotine and 5000 puffs. "
            "Magnetic connection. Compatible with the Lost Mary Psyper Device. "
            "Package contains 1 Lost Mary Psyper Prefilled Pod.",
            rules.CLOSED_REFILLS,
            "R10_POD_ONLY_REFILL",
        )

    def test_refill_pod_with_high_puff_count_is_closed_refills(self):
        self.assert_rescue(
            "Lost Mary Nera Fullview 70K Refill Pods",
            "Keep the flavor going with this refill pod for the Lost Mary Nera Fullview. "
            "Each pod is pre-filled with 5% nicotine and delivers 70,000 puffs.",
            rules.CLOSED_REFILLS,
            "R10_POD_ONLY_REFILL",
        )

    def test_prefilled_pod_pack_is_closed_refills(self):
        self.assert_rescue(
            "mbrand 50K Disposable Pods",
            "Two 25K puff pods click into place. Nicotine strength 5%. PREFILLED PODS. "
            "NON-REFILLABLE. Comes in a pack of two. INCLUDES: 2 mbrand Pods.",
            rules.CLOSED_REFILLS,
            "R10_POD_ONLY_REFILL",
        )

    def test_reusable_host_with_replace_when_done_lifecycle_is_closed_system(self):
        self.assert_rescue(
            "Pyne Pod Click 40K Disposable Vape",
            "Powered by a powerful detachable battery with pre-filled vape juice. "
            "Replace the pod when you are done using it. 40,000 puffs and two output modes.",
            rules.CLOSED_SYSTEM,
            "R11_REUSABLE_CLOSED_HOST",
        )

    def test_rechargeable_host_with_interchangeable_prefilled_capsules_is_closed_system(self):
        self.assert_rescue(
            "Logic Pro Starter Kit",
            "Starter kit with an internal 600mAh rechargeable battery and pre-filled 18mg "
            "disposable capsules. The easily interchangeable pre-filled disposable capsules "
            "keep the reusable device operating.",
            rules.CLOSED_SYSTEM,
            "R11_REUSABLE_CLOSED_HOST",
        )

    def test_complete_device_repeatedly_refilled_with_e_liquid_is_open_system(self):
        self.assert_rescue(
            "Asmodus Blank Bar Plus Refillable Disposable Vape",
            "This complete vape device can be refilled up to 10 times with any of your "
            "favorite e-liquid. It has a 650mAh battery and removable pod tank.",
            rules.OPEN_SYSTEM,
            "R12_REPEATED_E_LIQUID_REFILL",
        )

    def test_prefilled_self_powered_pod_is_still_disposable(self):
        result = classify_as_disposable(
            "Nova 25K Prefilled Pod",
            "Prefilled 5% pod with a 220mAh battery and draw-activated operation. "
            "The companion device is needed only for recharging.",
        )
        self.assertEqual(rules.DISPOSABLE, result["categories"])
        self.assertIsNone(result["policy_rule_id"])
        self.assertTrue(result["combination_device"])

    def test_modular_prefilled_disposable_without_reuse_lifecycle_stays_disposable(self):
        result = classify_as_disposable(
            "Geek Bar Clio Platinum 50K Disposable Kit",
            "Disposable kit with a separated kit battery, a large capacity prefilled pod, "
            "50,000 puffs, 5% nicotine, draw activation, and USB-C charging. "
            "Includes 1 Geek Bar Clio Platinum 50K Disposable Kit.",
        )
        self.assertEqual(rules.DISPOSABLE, result["categories"])
        self.assertIsNone(result["policy_rule_id"])
        self.assertTrue(result["combination_device"])

    def test_self_powered_pod_for_separate_host_is_combo_component(self):
        # R9a: kept visible as a component, but not counted as a full combo device.
        result = classify_as_disposable(
            "Off-Stamp Classic Cube X-Cube 25K Disposable Pods",
            "Pods Specifications: 100mAh Battery (Rechargeable via Off Stamp X-Cube Kit "
            "Battery Only), 18ml Pre Filled E-Liquid, 50mg.",
        )
        self.assertEqual(rules.DISPOSABLE, result["categories"])
        self.assertTrue(result["combo_component"])
        self.assertFalse(result["combination_device"])
        self.assertEqual("R9A_COMBO_COMPONENT", result["combo_rule_applied"])

    def test_screen_only_model_rationale_clears_combo_flag(self):
        # R9b: a detachable screen is not a modular battery/pod combination.
        result = rules.apply_category_policy(
            {
                "categories": rules.DISPOSABLE,
                "rationale": "Complete prefilled disposable.",
                "combination_device": True,
                "combination_device_rationale": (
                    "Image shows two separate pieces: device and detachable screen. "
                    "Text mentions 'detachable smart touch screen'."
                ),
            },
            {
                "product_name": "Whatabar Tik Tag 50K Disposable Vape",
                "site_category": "disposables",
                "site_tag": "",
                "description": "50K disposable pod pre-filled with 25ml e-juice. "
                               "A detachable smart touch screen is also available.",
                "eliquid_contents": "",
            },
        )
        self.assertFalse(result["combination_device"])
        self.assertFalse(result["combo_component"])
        self.assertEqual("R9B_CLEARED_SCREEN_ONLY", result["combo_rule_applied"])

    def test_battery_pod_model_rationale_keeps_combo_flag(self):
        # A rationale citing a battery/pod stays a combo, even if a screen is mentioned too.
        result = rules.apply_category_policy(
            {
                "categories": rules.DISPOSABLE,
                "rationale": "Complete prefilled disposable.",
                "combination_device": True,
                "combination_device_rationale": (
                    "Image shows separate battery and pod; display screen shows battery level."
                ),
            },
            {
                "product_name": "Kado Bar Snap 25K Kit Strawberry Banana",
                "site_category": "disposables",
                "site_tag": "",
                "description": "Kado Bar Snap 25K Kit includes: 1 - Kado Bar Snap Battery "
                               "1 - Kado Bar Snap Pod.",
                "eliquid_contents": "",
            },
        )
        self.assertTrue(result["combination_device"])
        self.assertFalse(result["combo_component"])
        self.assertIsNone(result["combo_rule_applied"])

    def test_generic_refillable_claim_without_repeated_e_liquid_evidence_stays_disposable(self):
        result = classify_as_disposable(
            "Orbit 30K Refillable Disposable Vape",
            "A 30K puff disposable with a rechargeable battery and replaceable magnetic pod. "
            "The product is refillable and has a snap-in connection.",
        )
        self.assertEqual(rules.DISPOSABLE, result["categories"])
        self.assertIsNone(result["policy_rule_id"])
        self.assertTrue(result["combination_device"])


if __name__ == "__main__":
    unittest.main(verbosity=2)