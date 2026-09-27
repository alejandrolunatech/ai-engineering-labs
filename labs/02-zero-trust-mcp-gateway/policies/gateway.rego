# Lab 02 — Zero-Trust MCP Gateway: Policy Decision Point.
#
# Evaluated by OPA for every MCP tool request. The gateway (PEP) must enforce
# the returned decision and treat anything other than allow == true as deny.
#
# Input contract (built by the gateway, not by the model):
#   principal.id, principal.role  TRUSTED   from gateway/application context
#   human_approved                TRUSTED   from a human approval workflow
#   environment, channel          TRUSTED   from gateway context (no rules yet)
#   tool.name                     UNTRUSTED requested by the model
#   arguments                     UNTRUSTED requested by the model
#
# Authority is only ever read from trusted fields. From `arguments` the policy
# reads exactly two values, amount_cents and reason, and only to *constrain* a
# refund. Nothing inside `arguments` can grant a permission.
package gateway

default decision := {
	"allow": false,
	"reason": "no policy rule permits this request",
	"rule_id": "deny.default",
}

# --- Policy data ------------------------------------------------------------

known_tools := {"get_order", "search_customer", "issue_refund", "export_customer_record"}

role_tools := {
	"auditor": {"get_order"},
	"support": {"get_order", "search_customer", "issue_refund"},
	"finance": {"get_order", "issue_refund"},
	"compliance": {"get_order", "search_customer", "export_customer_record"},
}

# Inclusive upper bound in integer cents: €50 and €500.
refund_limits_cents := {
	"support": 5000,
	"finance": 50000,
}

# --- Decision ---------------------------------------------------------------
#
# One ordered chain: the first matching branch wins, so exactly one decision
# is produced. The final allow branch re-proves every condition positively;
# if nothing matches, the default deny applies.

decision := {
	"allow": false,
	"reason": "trusted principal context is missing or malformed",
	"rule_id": "deny.missing_principal",
} if {
	not valid_principal
} else := {
	"allow": false,
	"reason": "principal role is not recognised",
	"rule_id": "deny.unknown_role",
} if {
	not role_tools[role]
} else := {
	"allow": false,
	"reason": "requested tool is not recognised",
	"rule_id": "deny.unknown_tool",
} if {
	not valid_tool
} else := {
	"allow": false,
	"reason": sprintf("role '%s' is not permitted to call '%s'", [role, tool]),
	"rule_id": "deny.tool_not_permitted_for_role",
} if {
	not tool in role_tools[role]
} else := {
	"allow": false,
	"reason": "refund amount must be a positive number",
	"rule_id": "deny.refund.invalid_amount",
} if {
	tool == "issue_refund"
	not valid_refund_amount
} else := {
	"allow": false,
	"reason": sprintf("refund amount exceeds the %v cent limit for role '%s'", [refund_limits_cents[role], role]),
	"rule_id": "deny.refund.over_limit",
} if {
	tool == "issue_refund"
	not refund_within_limit
} else := {
	"allow": false,
	"reason": "refund requires a non-empty reason",
	"rule_id": "deny.refund.missing_reason",
} if {
	tool == "issue_refund"
	not valid_refund_reason
} else := {
	"allow": false,
	"reason": "customer export requires trusted human approval",
	"rule_id": "deny.export.approval_required",
} if {
	tool == "export_customer_record"
	not trusted_human_approval
} else := {
	"allow": true,
	"reason": sprintf("role '%s' is permitted to call '%s'", [role, tool]),
	"rule_id": allow_rule_ids[tool],
} if {
	tool in role_tools[role]
	tool_conditions_met
}

allow_rule_ids := {
	"get_order": "allow.get_order",
	"search_customer": "allow.search_customer",
	"issue_refund": "allow.refund.within_limit",
	"export_customer_record": "allow.export.human_approved",
}

# --- Trusted context --------------------------------------------------------

role := input.principal.role

tool := input.tool.name

valid_principal if {
	is_string(input.principal.id)
	trim_space(input.principal.id) != ""
	is_string(input.principal.role)
}

# Negated as a whole: `not tool in known_tools` would be undefined (not true)
# when input.tool.name is missing, silently skipping this deny branch.
valid_tool if {
	is_string(input.tool.name)
	input.tool.name in known_tools
}

# Strict boolean true at the top level of the input. The string "true", a
# missing value, and anything under `arguments` do not count.
trusted_human_approval if input.human_approved == true

# --- Per-tool conditions ----------------------------------------------------

tool_conditions_met if tool in {"get_order", "search_customer"}

tool_conditions_met if {
	tool == "issue_refund"
	valid_refund_amount
	refund_within_limit
	valid_refund_reason
}

tool_conditions_met if {
	tool == "export_customer_record"
	trusted_human_approval
}

# --- Refund argument constraints (untrusted values, used only to restrict) --

valid_refund_amount if {
	is_number(input.arguments.amount_cents)
	input.arguments.amount_cents > 0
	input.arguments.amount_cents == floor(input.arguments.amount_cents)
}

refund_within_limit if {
	valid_refund_amount
	input.arguments.amount_cents <= refund_limits_cents[role]
}

valid_refund_reason if {
	is_string(input.arguments.reason)
	trim_space(input.arguments.reason) != ""
}
