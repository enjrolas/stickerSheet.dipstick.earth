"""
Reading and writing derivative files through Django's storage API.

The pipeline used to work in local filesystem paths (`self.media.path`).
That only exists on FileSystemStorage — S3Storage raises NotImplementedError —
so every derivative had to be routed through the storage API instead.

Pillow and ffmpeg both need real files on disk, so the shape is:

    with local_copy(sticker.media) as src:      # real path, or a temp copy
        imaging.make_thumb(src, tmp, ...)
        publish(tmp, 'captures/…/x.thumb.jpg')  # back into storage

On local storage `local_copy` hands back the real path and copies nothing, so
this costs nothing in the setup we have today.
"""

import contextlib
import os
import shutil
import tempfile

from django.core.files import File
from django.core.files.storage import default_storage


@contextlib.contextmanager
def local_copy(fieldfile, suffix=''):
    """
    Yield a filesystem path for `fieldfile`, downloading it if it is remote.

    A temp copy is deleted on the way out; a real path is left alone.
    """
    try:
        path = fieldfile.path
    except (NotImplementedError, ValueError, AttributeError):
        path = None

    if path and os.path.exists(path):
        yield path
        return

    if not suffix:
        suffix = os.path.splitext(fieldfile.name or '')[1]
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        fieldfile.open('rb')
        try:
            shutil.copyfileobj(fieldfile, handle)
        finally:
            fieldfile.close()
        handle.close()
        yield handle.name
    finally:
        try:
            os.remove(handle.name)
        except OSError:
            pass


def publish(local_path, name, storage=None):
    """
    Put a freshly built derivative into storage under exactly `name`.

    Deletes first: storage.save() would otherwise suffix the name on collision
    (foo.thumb_a8Kd2.jpg) and a rebuild would orphan the old file while the
    model went on pointing at a name that no longer matched.
    """
    storage = storage or default_storage
    if not local_path or not os.path.exists(local_path):
        return None
    if storage.exists(name):
        storage.delete(name)
    with open(local_path, 'rb') as fh:
        storage.save(name, File(fh))
    return name


@contextlib.contextmanager
def temp_path(suffix):
    """A path for something about to be written, cleaned up afterwards."""
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    handle.close()
    try:
        yield handle.name
    finally:
        try:
            os.remove(handle.name)
        except OSError:
            pass
