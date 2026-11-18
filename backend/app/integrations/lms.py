"""LMS integration (LTI / SCORM cloud). STUB.

TODO(lms): implement LTI 1.3 launch and grade passback once the LMS and its client
credentials are provisioned. Requires enterprise LMS configuration (not available here).
"""


class LmsClient:
    def publish_course_link(self, lo_id: str) -> None:
        raise NotImplementedError("TODO(lms): LMS integration requires enterprise LMS config")
