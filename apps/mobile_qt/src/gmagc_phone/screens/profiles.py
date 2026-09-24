"""Профили приборов (временная заглушка: редактор добавляется отдельным шагом)."""

from __future__ import annotations

from gmagc_common.i18n import t
from gmagc_phone.controller import PhoneController
from gmagc_phone.widgets import Page, label


class ProfilesScreen(Page):
    def __init__(self, controller: PhoneController):
        super().__init__(t("Профили приборов"), controller.close_overlay)
        self.controller = controller
        self.add(label(t("Профили приборов")))
        self.finish()
