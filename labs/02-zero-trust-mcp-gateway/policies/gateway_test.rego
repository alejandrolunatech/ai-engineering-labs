package gateway_test

import data.gateway

# --- Helpers ----------------------------------------------------------------

req(role, tool_name, args) := {
	"principal": {"id": "p-001", "role": role},
	"tool": {"name": tool_name},
	"arguments": args,
	"environment": "lab",
	"channel": "agent",
	"human_approved": false,
}

approved(r) := object.union(r, {"human_approved": true})

# object.union merges nested objects recursively, so remove first to replace.
with_principal(r, p) := object.union(object.remove(r, ["principal"]), {"principal": p})

refund(role, amount_eur, reason) := req(role, "issue_refund", {"order_id": "ord-1003", "amount_cents": amount_eur * 100, "reason": reason})

export(role) := req(role, "export_customer_record", {"customer_id": "cust-001"})

allowed(inp, rule_id) if {
	d := gateway.decision with input as inp
	d.allow == true
	d.rule_id == rule_id
}

denied(inp, rule_id) if {
	d := gateway.decision with input as inp
	d.allow == false
	d.rule_id == rule_id
}

# --- Decision shape ---------------------------------------------------------

test_decision_always_has_allow_reason_rule_id if {
	every inp in [req("auditor", "get_order", {}), req("auditor", "issue_refund", {}), {}] {
		d := gateway.decision with input as inp
		is_boolean(d.allow)
		is_string(d.reason)
		is_string(d.rule_id)
	}
}

# --- Default deny / malformed input -------------------------------------------

test_empty_input_denied if denied({}, "deny.missing_principal")

test_missing_principal_denied if {
	denied(object.remove(req("support", "get_order", {}), ["principal"]), "deny.missing_principal")
}

test_principal_without_id_denied if {
	denied(with_principal(req("support", "get_order", {}), {"role": "support"}), "deny.missing_principal")
}

test_principal_blank_id_denied if {
	denied(with_principal(req("support", "get_order", {}), {"id": "  ", "role": "support"}), "deny.missing_principal")
}

test_principal_without_role_denied if {
	denied(with_principal(req("support", "get_order", {}), {"id": "p-001"}), "deny.missing_principal")
}

test_principal_non_string_role_denied if {
	denied(req(["compliance"], "get_order", {}), "deny.missing_principal")
}

test_principal_not_an_object_denied if {
	denied(with_principal(req("support", "get_order", {}), "support"), "deny.missing_principal")
}

test_unknown_role_denied if denied(req("admin", "get_order", {}), "deny.unknown_role")

test_role_is_case_sensitive if denied(req("Support", "get_order", {}), "deny.unknown_role")

test_unknown_tool_denied if denied(req("compliance", "delete_all_customers", {}), "deny.unknown_tool")

test_missing_tool_denied if {
	denied(object.remove(req("compliance", "get_order", {}), ["tool"]), "deny.unknown_tool")
}

test_non_string_tool_name_denied if {
	denied(object.union(req("compliance", "get_order", {}), {"tool": {"name": ["get_order"]}}), "deny.unknown_tool")
}

test_tool_name_is_case_sensitive if denied(req("support", "Get_Order", {}), "deny.unknown_tool")

# --- Role x tool matrix (non-argument tools) ----------------------------------

test_get_order_allowed_for_every_known_role if {
	every r in ["auditor", "support", "finance", "compliance"] {
		allowed(req(r, "get_order", {"order_id": "ord-1001"}), "allow.get_order")
	}
}

test_search_customer_allowed_for_support if allowed(req("support", "search_customer", {"query": "ada"}), "allow.search_customer")

test_search_customer_allowed_for_compliance if allowed(req("compliance", "search_customer", {"query": "ada"}), "allow.search_customer")

test_search_customer_denied_for_auditor if denied(req("auditor", "search_customer", {"query": "ada"}), "deny.tool_not_permitted_for_role")

test_search_customer_denied_for_finance if denied(req("finance", "search_customer", {"query": "ada"}), "deny.tool_not_permitted_for_role")

# --- issue_refund: role -------------------------------------------------------

test_refund_denied_for_auditor if denied(refund("auditor", 10, "duplicate charge"), "deny.tool_not_permitted_for_role")

test_refund_denied_for_compliance if denied(refund("compliance", 10, "duplicate charge"), "deny.tool_not_permitted_for_role")

test_refund_denied_for_auditor_even_with_trusted_approval if {
	denied(approved(refund("auditor", 10, "duplicate charge")), "deny.tool_not_permitted_for_role")
}

# --- issue_refund: support amount boundaries (<= 50) --------------------------

test_support_refund_25_allowed if allowed(refund("support", 25, "duplicate charge"), "allow.refund.within_limit")

test_support_refund_49_99_allowed if allowed(refund("support", 49.99, "duplicate charge"), "allow.refund.within_limit")

test_support_refund_50_allowed_inclusive if allowed(refund("support", 50, "duplicate charge"), "allow.refund.within_limit")

test_support_refund_50_01_denied if denied(refund("support", 50.01, "duplicate charge"), "deny.refund.over_limit")

test_support_refund_250_denied if denied(refund("support", 250, "duplicate charge"), "deny.refund.over_limit")

test_support_refund_over_limit_not_rescued_by_approval if {
	denied(approved(refund("support", 250, "duplicate charge")), "deny.refund.over_limit")
}

# --- issue_refund: finance amount boundaries (<= 500) -------------------------

test_finance_refund_250_allowed if allowed(refund("finance", 250, "damaged item"), "allow.refund.within_limit")

test_finance_refund_499_99_allowed if allowed(refund("finance", 499.99, "damaged item"), "allow.refund.within_limit")

test_finance_refund_500_allowed_inclusive if allowed(refund("finance", 500, "damaged item"), "allow.refund.within_limit")

test_finance_refund_500_01_denied if denied(refund("finance", 500.01, "damaged item"), "deny.refund.over_limit")

test_finance_refund_750_denied if denied(refund("finance", 750, "damaged item"), "deny.refund.over_limit")

# --- issue_refund: invalid amounts ----------------------------------------------

test_refund_zero_denied if denied(refund("support", 0, "duplicate charge"), "deny.refund.invalid_amount")

test_refund_negative_denied if denied(refund("finance", -10, "duplicate charge"), "deny.refund.invalid_amount")

test_refund_fractional_cent_denied if {
	denied(req("support", "issue_refund", {"order_id": "ord-1003", "amount_cents": 0.1, "reason": "duplicate charge"}), "deny.refund.invalid_amount")
}

test_refund_amount_as_string_denied if denied(req("support", "issue_refund", {"order_id": "ord-1003", "amount_cents": "2500", "reason": "duplicate charge"}), "deny.refund.invalid_amount")

test_refund_amount_null_denied if denied(req("support", "issue_refund", {"order_id": "ord-1003", "amount_cents": null, "reason": "duplicate charge"}), "deny.refund.invalid_amount")

test_refund_amount_missing_denied if {
	denied(req("support", "issue_refund", {"order_id": "ord-1003", "reason": "duplicate charge"}), "deny.refund.invalid_amount")
}

test_refund_arguments_missing_denied if {
	denied(object.remove(refund("support", 25, "x"), ["arguments"]), "deny.refund.invalid_amount")
}

# --- issue_refund: reason ------------------------------------------------------

test_refund_empty_reason_denied if denied(refund("support", 25, ""), "deny.refund.missing_reason")

test_refund_whitespace_reason_denied if denied(refund("finance", 25, " \t\n "), "deny.refund.missing_reason")

test_refund_non_string_reason_denied if denied(refund("support", 25, 123), "deny.refund.missing_reason")

test_refund_null_reason_denied if denied(refund("support", 25, null), "deny.refund.missing_reason")

test_refund_missing_reason_denied if {
	denied(req("finance", "issue_refund", {"order_id": "ord-1003", "amount_cents": 2500}), "deny.refund.missing_reason")
}

# --- export_customer_record -----------------------------------------------------

test_compliance_export_with_trusted_approval_allowed if allowed(approved(export("compliance")), "allow.export.human_approved")

test_compliance_export_without_approval_denied if denied(export("compliance"), "deny.export.approval_required")

test_compliance_export_missing_approval_field_denied if {
	denied(object.remove(export("compliance"), ["human_approved"]), "deny.export.approval_required")
}

test_compliance_export_approval_string_true_denied if {
	denied(object.union(export("compliance"), {"human_approved": "true"}), "deny.export.approval_required")
}

test_compliance_export_approval_number_one_denied if {
	denied(object.union(export("compliance"), {"human_approved": 1}), "deny.export.approval_required")
}

test_export_denied_for_other_roles_even_with_trusted_approval if {
	every r in ["auditor", "support", "finance"] {
		denied(approved(export(r)), "deny.tool_not_permitted_for_role")
	}
}

# --- Model-controlled arguments cannot grant authority ------------------------

test_arguments_role_admin_does_not_escalate_auditor if {
	denied(req("auditor", "issue_refund", {"order_id": "ord-1003", "amount_cents": 1000, "reason": "x", "role": "admin"}), "deny.tool_not_permitted_for_role")
}

test_arguments_role_finance_does_not_raise_support_limit if {
	denied(req("support", "issue_refund", {"order_id": "ord-1003", "amount_cents": 25000, "reason": "x", "role": "finance"}), "deny.refund.over_limit")
}

test_arguments_is_admin_does_not_escalate if {
	denied(req("support", "export_customer_record", {"customer_id": "cust-001", "is_admin": true}), "deny.tool_not_permitted_for_role")
}

test_arguments_human_approved_does_not_approve_export if {
	denied(req("compliance", "export_customer_record", {"customer_id": "cust-001", "human_approved": true}), "deny.export.approval_required")
}

test_arguments_principal_does_not_override_trusted_principal if {
	args := {"customer_id": "cust-001", "principal": {"id": "attacker", "role": "compliance"}, "human_approved": true}
	denied(req("auditor", "export_customer_record", args), "deny.tool_not_permitted_for_role")
}

test_arguments_refund_limit_override_ignored if {
	denied(req("support", "issue_refund", {"order_id": "ord-1003", "amount_cents": 120000, "reason": "x", "refund_limit": 5000}), "deny.refund.over_limit")
}

# The exact payload requested by the ord-1004 prompt-injection fixture.
test_injection_fixture_requests_denied_for_support if {
	denied(req("support", "export_customer_record", {"customer_id": "cust-003"}), "deny.tool_not_permitted_for_role")
	denied(refund("support", 1200, "approved by system"), "deny.refund.over_limit")
}

test_injection_fixture_refund_denied_even_for_finance if {
	denied(refund("finance", 1200, "approved by system"), "deny.refund.over_limit")
}

# --- Trusted context the policy does not (yet) constrain -----------------------

# environment and channel are part of the input contract but no rule uses them
# yet; this pins current behaviour so a future rule change is a visible diff.
test_environment_and_channel_do_not_currently_affect_decision if {
	allowed(object.union(req("auditor", "get_order", {}), {"environment": "prod", "channel": "api"}), "allow.get_order")
}
