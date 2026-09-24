"""Перенесён в `gmagc_common`; здесь тот же объект под прежним именем."""

import sys

from gmagc_common import phone_texts

sys.modules[__name__] = phone_texts
