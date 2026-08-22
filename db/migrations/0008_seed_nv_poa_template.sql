-- Seeds the v1 Legal-drafting template: Nevada durable financial power of attorney,
-- modeled on the statutory form at NRS 162A.620 (Uniform Power of Attorney Act).
--
-- *** NEEDS JASON'S LEGAL REVIEW BEFORE THIS SHIPS. ***
-- is_active is FALSE on purpose: the drafted body_template/schema_json below are a
-- good-faith first pass at NRS 162A.620's structure (principal/agent/alternate-agent
-- designation, subject-by-subject granted powers, durability election, special
-- instructions, signature block), not verbatim statute text, and have not been checked
-- against the current statute or reviewed by a licensed Nevada attorney. The template is
-- invisible to every /legal endpoint (list/get both filter is_active = TRUE) until that
-- review happens and a follow-up migration flips this row to TRUE.

INSERT INTO legal_templates (
    legal_template_id, slug, version, title, category, jurisdiction_note,
    schema_json, body_template, disclaimer_text, is_active
) VALUES (
    'c1d9e2a4-7b3f-4e5a-9c1d-2f3a4b5c6d01',
    'nv-poa-financial',
    1,
    'Nevada Durable Financial Power of Attorney',
    'Legal',
    $jn$Nevada only (NRS 162A). This grants authority over your property and financial affairs while you are alive — it does NOT cover health care decisions, and it terminates automatically at your death. It gives your agent no authority over who receives your property afterward. If you want to control what happens to your property when you die, you need a will and/or beneficiary or transfer-on-death designations — not a power of attorney.$jn$,
    $schema${
        "principal_name": {"type": "text", "label": "Your full legal name (Principal)", "required": true,
            "help": "The person granting power of attorney — that is you."},
        "principal_address": {"type": "text", "label": "Your address", "required": true},
        "agent_name": {"type": "text", "label": "Agent full legal name", "required": true,
            "help": "The person you are authorizing to act for you."},
        "agent_address": {"type": "text", "label": "Agent address", "required": true},
        "agent_phone": {"type": "text", "label": "Agent phone number", "required": false},
        "first_alternate_agent_name": {"type": "text", "label": "First alternate agent (optional)",
            "required": false, "help": "Steps in if your first agent cannot or will not serve."},
        "first_alternate_agent_address": {"type": "text", "label": "First alternate agent address",
            "required": false},
        "second_alternate_agent_name": {"type": "text", "label": "Second alternate agent (optional)",
            "required": false},
        "second_alternate_agent_address": {"type": "text", "label": "Second alternate agent address",
            "required": false},
        "granted_powers": {"type": "multiselect", "label": "Powers granted to your agent", "required": true,
            "help": "Under NRS 162A, general authority is granted subject by subject — select every area your agent should be able to act in.",
            "options": ["Real Property", "Tangible Personal Property", "Stocks and Bonds",
                "Commodities and Options", "Banks and Other Financial Institutions", "Safe Deposit Boxes",
                "Operation of Entity or Business", "Insurance and Annuities",
                "Estates, Trusts, and Other Beneficial Interests", "Legal Affairs, Claims, and Litigation",
                "Personal and Family Maintenance",
                "Benefits from Governmental Programs or Civil or Military Service",
                "Retirement Plans", "Taxes"]},
        "durability_election": {"type": "select", "label": "When does this take effect?", "required": true,
            "options": ["Immediately, and remains effective if I become incapacitated (durable)",
                "Only if and when I become incapacitated (springing)"]},
        "special_instructions": {"type": "textarea", "label": "Special instructions or limitations (optional)",
            "required": false},
        "effective_date": {"type": "date", "label": "Date of signing", "required": true},
        "signing_city": {"type": "text", "label": "City where you are signing", "required": true},
        "signing_county": {"type": "text", "label": "County where you are signing", "required": true}
    }$schema$::jsonb,
    $body$NEVADA DURABLE POWER OF ATTORNEY FOR FINANCIAL AFFAIRS
Nevada Revised Statutes Chapter 162A

NOTICE TO PRINCIPAL: This document gives the person you designate as your agent the power to make decisions concerning your property for you. This document does not authorize anyone to make health care decisions for you.

1. DESIGNATION OF PRINCIPAL AND AGENT
I, {principal_name}, of {principal_address}, appoint {agent_name}, of {agent_address}, telephone {agent_phone}, as my Agent (my attorney-in-fact) to act for me in the manner authorized below.

2. DESIGNATION OF ALTERNATE AGENTS
If my Agent named above is unable or unwilling to serve, I appoint {first_alternate_agent_name}, of {first_alternate_agent_address}, as my First Alternate Agent. If neither is able or willing to serve, I appoint {second_alternate_agent_name}, of {second_alternate_agent_address}, as my Second Alternate Agent.

3. GRANT OF GENERAL AUTHORITY
I grant my Agent general authority to act for me with respect to the following subjects as defined in NRS Chapter 162A: {granted_powers}.

4. DURABILITY
{durability_election}

5. SPECIAL INSTRUCTIONS
{special_instructions}

6. TERMINATION
This power of attorney terminates automatically on my death, on my revocation of it, or as otherwise provided by NRS Chapter 162A. It does not control the disposition of my property after my death; that is governed by my will, trust, or applicable beneficiary and transfer-on-death designations, if any.

7. SIGNATURE
Signed this {effective_date}, at {signing_city}, {signing_county} County, Nevada.

_________________________________
{principal_name}, Principal

[Notary acknowledgment block per NRS 162A to be completed at signing — this document is not valid until properly signed and notarized.]$body$,
    $disc$Drafted with CanI — not legal advice, not reviewed by an attorney. This draft has not been checked against the current text of NRS Chapter 162A and should be reviewed by a licensed Nevada attorney, and properly signed and notarized, before use.$disc$,
    FALSE
) ON CONFLICT (slug, version) DO NOTHING;
