"""Third-party content vendor ingestion. STUB.

TODO(vendor): fetch packages from vendor catalogs and create draft learning objects. Requires
vendor API credentials and contract terms (not available here).
"""


class VendorClient:
    def import_package(self, vendor_id: str, package_ref: str) -> str:
        raise NotImplementedError("TODO(vendor): requires vendor API credentials")
