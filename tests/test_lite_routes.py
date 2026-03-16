from services.api import lite_routes


class _UploadLike:
    def __init__(self):
        self.file = object()
        self.filename = "video.mp4"


def test_is_uploaded_file_accepts_upload_like_objects() -> None:
    assert lite_routes._is_uploaded_file(_UploadLike()) is True
    assert lite_routes._is_uploaded_file(None) is False
    assert lite_routes._is_uploaded_file(object()) is False
