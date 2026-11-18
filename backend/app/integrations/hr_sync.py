"""HR / directory sync (SCIM or HRIS feed). STUB.

TODO(hr-sync): pull user, role, and org data from the HRIS or SCIM endpoint into the users
and roles tables. Requires enterprise SSO/SCIM configuration (not available here).
"""


class HrSyncClient:
    def sync_users(self) -> int:
        raise NotImplementedError("TODO(hr-sync): requires SCIM/HRIS configuration")
