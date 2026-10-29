# ROLES_V1
"""Role lookup layer.

The old roles (DIRECTOR, MANAGER, RETAIL, TELECOM, MULTICHOICE) are untouched.
Three newer roles are described here as combinations of abilities, so the rest
of the site can ask "may this person act as Retail?" instead of comparing names.

    RETAIL_TELECOM  Retail + Telecom Staff        -> acts as RETAIL and TELECOM
    RETAIL_LEAD     Retail + Manager-level report -> acts as RETAIL, plus branch duties
                    (record expenses, daily WhatsApp report, device commission)
    SUB_DIRECTOR    approves stock for the Director, in every branch

Any user (of any role) can also be given the "branch duties" switch in the
admin page, which adds BRANCH_DUTIES to what they can do.
"""

RETAIL_TELECOM = "RETAIL_TELECOM"
RETAIL_LEAD = "RETAIL_LEAD"
SUB_DIRECTOR = "SUB_DIRECTOR"

NEW_ROLE_CHOICES = (
    (RETAIL_TELECOM, "Retail + Telecom Staff"),
    (RETAIL_LEAD, "Retail + Manager-level Report"),
    (SUB_DIRECTOR, "Sub Director"),
)

# what each role may act as, besides itself
_ALSO_ACTS_AS = {
    RETAIL_TELECOM: {"RETAIL", "TELECOM"},
    RETAIL_LEAD: {"RETAIL", "BRANCH_DUTIES"},
    SUB_DIRECTOR: set(),
}

# every role that holds stock and sells (used for staff lists)
STAFF_ROLES = ("RETAIL", "TELECOM", "MULTICHOICE", RETAIL_TELECOM, RETAIL_LEAD)

# roles that are Director-level people and not branch staff
DIRECTOR_LEVEL = ("DIRECTOR", "SUPERADMIN", SUB_DIRECTOR)


def effective_roles(user):
    """The set of role names this user may act as."""
    role = getattr(user, "role", "") or ""
    acts = {role} | _ALSO_ACTS_AS.get(role, set())
    if getattr(user, "branch_duties", False):
        acts.add("BRANCH_DUTIES")
    return acts


def has_role(user, *names):
    """True if the user may act as any of the named roles."""
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(effective_roles(user) & set(names))


def roles_for(name):
    """Every stored role value that may act as `name` (for queries such as role__in=...)."""
    out = [name]
    for role, acts in _ALSO_ACTS_AS.items():
        if name in acts and role not in out:
            out.append(role)
    return out
