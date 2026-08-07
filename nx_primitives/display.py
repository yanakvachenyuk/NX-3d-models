from __future__ import annotations

import NXOpen

from .base import Profile


class Hide:
    """
    Скрывает двумерные кривые профилей.
    """

    def __init__(
        self,
        session: NXOpen.Session,
        *profiles: Profile
    ):

        objects = []

        for profile in profiles:

            objects.extend(profile.curves)

        if objects:

            session.DisplayManager.BlankObjects(objects)