"""Nine canonical roles. Legacy token labels are normalized at the trust boundary."""

from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "Super Administrator"
    ADMIN = "Super Administrator"
    REPOSITORY_ADMIN = "Repository Administrator"
    CREATOR = "Content Creator"
    CONTRIBUTOR = "Content Creator"
    REVIEWER = "Reviewer"
    APPROVER = "Approver"
    PUBLISHER = "Publisher"
    INSTRUCTOR = "Instructor"
    LEARNER = "Learner"
    READ_ONLY = "Read-Only User"


ROLE_ALIASES = {"Admin": Role.SUPER_ADMIN.value, "Contributor": Role.CREATOR.value}
READ = {"content.read", "content.download", "favorites.write", "activity.write"}
ROLE_PERMISSIONS = {
    Role.READ_ONLY.value: {"content.read"},
    Role.LEARNER.value: READ,
    Role.INSTRUCTOR.value: READ | {"collections.write"},
    Role.CREATOR.value: READ
    | {"content.create", "content.edit", "workflow.submit", "collections.write"},
    Role.REVIEWER.value: READ | {"workflow.review"},
    Role.APPROVER.value: READ | {"workflow.approve"},
    Role.PUBLISHER.value: READ | {"workflow.publish"},
    Role.REPOSITORY_ADMIN.value: READ
    | {
        "content.create",
        "content.edit",
        "content.manage",
        "workflow.submit",
        "workflow.review",
        "workflow.approve",
        "workflow.publish",
        "collections.write",
        "organization.manage",
        "reports.read",
        "workflow.assign",
        "workflow.policy",
        "metadata.manage",
    },
    Role.SUPER_ADMIN.value: {"*"},
}


def canonical(roles):
    return frozenset(
        ROLE_ALIASES.get(str(role), str(role))
        for role in roles
        if ROLE_ALIASES.get(str(role), str(role)) in ROLE_PERMISSIONS
    )


def permissions_for(roles):
    return frozenset(p for role in canonical(roles) for p in ROLE_PERMISSIONS[role])
